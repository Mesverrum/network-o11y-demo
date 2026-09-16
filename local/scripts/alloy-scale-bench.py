#!/usr/bin/env python3
"""1-CPU Alloy scale bench: 48-port SNMP sims + syslog / trap / flow EPS.

Does not touch the colocated Clos. Runs a throwaway Alloy on host networking
(`srl-local/alloy:network-dev`) pinned to GOMAXPROCS=1.

  python3 local/scripts/alloy-scale-bench.py
  python3 local/scripts/alloy-scale-bench.py --devices 20 --skip-events
  python3 local/scripts/alloy-scale-bench.py --skip-snmp --eps-max 4000

Writes report.json + report.md under --out (default /tmp/alloy-scale-bench).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("ALLOY_IMAGE", "srl-local/alloy:network-dev")
NAME = "alloy-scale-bench"
METRICS = "http://127.0.0.1:19192/metrics"
SYSLOG_PORT = 2514
TRAP_PORT = 21620
FLOW_PORT = 22055
SINK_PORT = 14318
SNMP_BASE = 16101

# NetFlow v9 IEs (same grain as send-flow-samples.py).
NF_FIELDS = [
    (8, 4),
    (12, 4),
    (22, 4),
    (21, 4),
    (1, 4),
    (2, 4),
    (10, 2),
    (14, 2),
    (7, 2),
    (11, 2),
    (4, 1),
    (6, 1),
    (60, 1),
    (5, 1),
]
NF_TID = 3000
NF_SID = 0xB001


# --- tiny SNMP v2c ---------------------------------------------------------


def _ber_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, val: bytes) -> bytes:
    return bytes([tag]) + _ber_len(len(val)) + val


def _int(n: int) -> bytes:
    if n == 0:
        return _tlv(0x02, b"\x00")
    length = max(1, (n.bit_length() + 8) // 8)
    raw = n.to_bytes(length, "big", signed=True)
    return _tlv(0x02, raw)


def _oid(parts: tuple[int, ...]) -> bytes:
    out = bytearray([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        if p < 0:
            raise ValueError(p)
        if p < 128:
            out.append(p)
            continue
        stack = [p & 0x7F]
        p >>= 7
        while p:
            stack.append(0x80 | (p & 0x7F))
            p >>= 7
        out.extend(reversed(stack))
    return _tlv(0x06, bytes(out))


def _parse_len(buf: bytes, i: int) -> tuple[int, int]:
    first = buf[i]
    if first < 0x80:
        return first, i + 1
    n = first & 0x7F
    return int.from_bytes(buf[i + 1 : i + 1 + n], "big"), i + 1 + n


def _parse_tlv(buf: bytes, i: int) -> tuple[int, bytes, int]:
    tag = buf[i]
    ln, j = _parse_len(buf, i + 1)
    return tag, buf[j : j + ln], j + ln


def _parse_int(val: bytes) -> int:
    return int.from_bytes(val, "big", signed=True)


def _parse_oid(val: bytes) -> tuple[int, ...]:
    if not val:
        return ()
    first = val[0]
    parts = [first // 40, first % 40]
    n = 0
    for b in val[1:]:
        n = (n << 7) | (b & 0x7F)
        if b < 0x80:
            parts.append(n)
            n = 0
    return tuple(parts)


def encode_varbind(oid: tuple[int, ...], tag: int, raw: bytes) -> bytes:
    return _tlv(0x30, _oid(oid) + _tlv(tag, raw))


def encode_response(req_id: int, vbs: list[bytes], err: int = 0, idx: int = 0) -> bytes:
    pdu = (
        _int(req_id)
        + _int(err)
        + _int(idx)
        + _tlv(0x30, b"".join(vbs))
    )
    msg = _int(1) + _tlv(0x04, b"public") + _tlv(0xA2, pdu)
    return _tlv(0x30, msg)


def _oid_value(parts: tuple[int, ...]) -> bytes:
    tlv = _oid(parts)
    _, val, _ = _parse_tlv(tlv, 0)
    return val


def encode_trap(trap_oid: tuple[int, ...], extra: list[bytes]) -> bytes:
    uptime = int(time.monotonic() * 100) % 2_147_000_000
    vbs = [
        encode_varbind((1, 3, 6, 1, 2, 1, 1, 3, 0), 0x43, uptime.to_bytes(4, "big")),
        encode_varbind((1, 3, 6, 1, 6, 3, 1, 1, 4, 1, 0), 0x06, _oid_value(trap_oid)),
        *extra,
    ]
    pdu = _int(int(time.time()) & 0x7FFFFFFF) + _int(0) + _int(0) + _tlv(0x30, b"".join(vbs))
    return _tlv(0x30, _int(1) + _tlv(0x04, b"public") + _tlv(0xA7, pdu))


def _ticks(n: int) -> bytes:
    return n.to_bytes(4, "big")


def _u32(n: int) -> bytes:
    return (n & 0xFFFFFFFF).to_bytes(4, "big")


def _u64(n: int) -> bytes:
    return (n & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")


def build_switch_tree(name: str, nports: int, seed: int) -> list[tuple[tuple[int, ...], int, bytes]]:
    """IF-MIB + SNMPv2-MIB enough for device_base / if_mib / if_mib_meta."""
    rows: list[tuple[tuple[int, ...], int, bytes]] = []
    sysoid = (1, 3, 6, 1, 4, 1, 99999, 48)  # unknown vendor → device_base + if_mib
    rows += [
        ((1, 3, 6, 1, 2, 1, 1, 1, 0), 0x04, f"Alloy scale bench 48-port ({name})".encode()),
        ((1, 3, 6, 1, 2, 1, 1, 2, 0), 0x06, _oid_value(sysoid)),
        ((1, 3, 6, 1, 2, 1, 1, 3, 0), 0x43, _ticks(123456)),
        ((1, 3, 6, 1, 2, 1, 1, 4, 0), 0x04, b"lab"),
        ((1, 3, 6, 1, 2, 1, 1, 5, 0), 0x04, name.encode()),
        ((1, 3, 6, 1, 2, 1, 1, 6, 0), 0x04, b"bench-rack"),
        ((1, 3, 6, 1, 2, 1, 2, 1, 0), 0x02, bytes([nports])),
    ]
    for i in range(1, nports + 1):
        mac = bytes([0x02, 0x00, 0x00, seed & 0xFF, (i >> 8) & 0xFF, i & 0xFF])
        iname = f"Gi1/0/{i}".encode()
        rows += [
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 1, i), 0x02, bytes([i] if i < 128 else i.to_bytes(2, "big"))),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 2, i), 0x04, iname),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 3, i), 0x02, bytes([6])),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 6, i), 0x04, mac),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 7, i), 0x02, bytes([1])),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 8, i), 0x02, bytes([1])),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 13, i), 0x41, _u32(0)),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 14, i), 0x41, _u32(i % 3)),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 19, i), 0x41, _u32(0)),
            ((1, 3, 6, 1, 2, 1, 2, 2, 1, 20, i), 0x41, _u32(0)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 1, i), 0x04, iname),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 6, i), 0x46, _u64(1_000_000 * i)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 7, i), 0x46, _u64(1000 * i)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 8, i), 0x46, _u32(0)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 9, i), 0x46, _u32(0)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 10, i), 0x46, _u64(800_000 * i)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 11, i), 0x46, _u64(800 * i)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 12, i), 0x46, _u32(0)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 13, i), 0x46, _u32(0)),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 15, i), 0x42, (1000).to_bytes(4, "big")),
            ((1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 18, i), 0x04, f"port-{i}".encode()),
        ]
    rows.sort(key=lambda r: r[0])
    return rows


class SnmpFarm:
    def __init__(self, devices: int, ports: int):
        self.devices = devices
        self.ports = ports
        self._socks: list[socket.socket] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.trees = [
            build_switch_tree(f"sw-{i:03d}", ports, i) for i in range(1, devices + 1)
        ]

    def start(self) -> None:
        for i, tree in enumerate(self.trees):
            port = SNMP_BASE + i
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", port))
            sock.settimeout(0.3)
            self._socks.append(sock)
            t = threading.Thread(target=self._serve, args=(sock, tree), daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for s in self._socks:
            s.close()

    def _serve(self, sock: socket.socket, tree: list) -> None:
        oids = [row[0] for row in tree]
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(65535)
            except (TimeoutError, OSError):
                continue
            try:
                resp = self._answer(data, tree, oids)
            except Exception:
                continue
            if resp:
                try:
                    sock.sendto(resp, addr)
                except OSError:
                    pass

    def _answer(self, data: bytes, tree: list, oids: list) -> bytes | None:
        tag, body, _ = _parse_tlv(data, 0)
        if tag != 0x30:
            return None
        i = 0
        _, _, i = _parse_tlv(body, i)  # version
        _, comm, i = _parse_tlv(body, i)
        if comm != b"public":
            return None
        pdu_tag, pdu, _ = _parse_tlv(body, i)
        if pdu_tag not in (0xA0, 0xA1):
            return None
        j = 0
        _, rid_raw, j = _parse_tlv(pdu, j)
        req_id = _parse_int(rid_raw)
        _, _, j = _parse_tlv(pdu, j)
        _, _, j = _parse_tlv(pdu, j)
        _, vbl, _ = _parse_tlv(pdu, j)
        out: list[bytes] = []
        k = 0
        while k < len(vbl):
            _, vb, k = _parse_tlv(vbl, k)
            _, oid_raw, m = _parse_tlv(vb, 0)
            oid = _parse_oid(oid_raw)
            if pdu_tag == 0xA0:
                hit = next((row for row in tree if row[0] == oid), None)
                if hit is None:
                    out.append(encode_varbind(oid, 0x80, b""))  # noSuchObject
                else:
                    out.append(encode_varbind(hit[0], hit[1], hit[2]))
            else:
                nxt = None
                for idx, key in enumerate(oids):
                    if key > oid:
                        nxt = tree[idx]
                        break
                if nxt is None:
                    out.append(encode_varbind(oid, 0x82, b""))  # endOfMibView
                else:
                    out.append(encode_varbind(nxt[0], nxt[1], nxt[2]))
        return encode_response(req_id, out)


# --- OTLP blackhole --------------------------------------------------------


class _Sink(BaseHTTPRequestHandler):
    counts = {"metrics": 0, "logs": 0, "bytes": 0}

    def log_message(self, *_a) -> None:
        return

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        _Sink.counts["bytes"] += n
        if "logs" in self.path:
            _Sink.counts["logs"] += 1
        else:
            _Sink.counts["metrics"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


def start_sink() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", SINK_PORT), _Sink)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# --- Alloy config + docker -------------------------------------------------


def merge_snmp_yml(out: Path) -> None:
    mods = []
    for name in ("device_base.yml", "if_mib.yml", "if_mib_meta.yml"):
        text = (ROOT / "fixtures/alloy-snmp/modules/_general" / name).read_text(encoding="utf-8")
        chunk = text.split("modules:\n", 1)[1]
        mods.append(chunk.rstrip() + "\n")
    out.write_text(
        "auths:\n  public_v2:\n    community: public\n    version: 2\nmodules:\n" + "".join(mods),
        encoding="utf-8",
    )


def write_alloy(path: Path, devices: int, mode: str) -> None:
    """mode: snmp | events"""
    lines = [
        "// generated by alloy-scale-bench.py",
        'otelcol.exporter.otlphttp "sink" {',
        "  client {",
        f'    endpoint = "http://127.0.0.1:{SINK_PORT}"',
        "    tls { insecure = true }",
        "  }",
        "}",
        "",
        'otelcol.processor.batch "out" {',
        "  timeout = \"1s\"",
        "  output {",
        "    metrics = [otelcol.exporter.otlphttp.sink.input]",
        "    logs    = [otelcol.exporter.otlphttp.sink.input]",
        "  }",
        "}",
        "",
        'prometheus.exporter.self "alloy" {}',
        'prometheus.scrape "self" {',
        "  targets         = prometheus.exporter.self.alloy.targets",
        '  scrape_interval = "15s"',
        '  scrape_timeout  = "10s"',
        "  forward_to      = [otelcol.receiver.prometheus.local.receiver]",
        "}",
        "",
        'otelcol.receiver.prometheus "local" {',
        "  output { metrics = [otelcol.processor.batch.out.input] }",
        "}",
        "",
    ]
    if mode == "snmp":
        def target_maps(module: str) -> list[str]:
            rows = ["  targets = ["]
            for i in range(devices):
                rows.append(
                    "    {"
                    f' name = "sw-{i+1:03d}",'
                    f' address = "127.0.0.1:{SNMP_BASE + i}",'
                    f' module = "{module}",'
                    ' auth = "public_v2",'
                    " },"
                )
            rows.append("  ]")
            return rows

        lines += [
            'prometheus.exporter.snmp "hot" {',
            '  config_file           = "/etc/alloy/snmp-network.yml"',
            '  config_merge_strategy = "replace"',
        ]
        lines += target_maps("if_mib,device_base")
        lines += [
            "}",
            "",
            'prometheus.exporter.snmp "cold" {',
            '  config_file           = "/etc/alloy/snmp-network.yml"',
            '  config_merge_strategy = "replace"',
        ]
        lines += target_maps("if_mib_meta")
        lines += [
            "}",
            "",
            'prometheus.relabel "job" {',
            "  forward_to = [otelcol.receiver.prometheus.local.receiver]",
            "  rule {",
            '    target_label = "job"',
            '    replacement  = "alloy-snmp"',
            "  }",
            "}",
            "",
            'prometheus.scrape "hot" {',
            "  targets         = prometheus.exporter.snmp.hot.targets",
            '  scrape_interval = "30s"',
            '  scrape_timeout  = "25s"',
            "  forward_to      = [prometheus.relabel.job.receiver]",
            "}",
            "",
            'prometheus.scrape "cold" {',
            "  targets         = prometheus.exporter.snmp.cold.targets",
            '  scrape_interval = "90s"',
            '  scrape_timeout  = "60s"',
            "  forward_to      = [prometheus.relabel.job.receiver]",
            "}",
            "",
        ]
    else:
        lines += [
            'otelcol.receiver.syslog "bench" {',
            '  protocol = "none"',
            '  on_error = "send"',
            "  udp {",
            f'    listen_address = "0.0.0.0:{SYSLOG_PORT}"',
            "    add_attributes = true",
            "  }",
            "  output { logs = [otelcol.processor.batch.out.input] }",
            "}",
            "",
            'otelcol.receiver.snmptrap "bench" {',
            f'  listen_address = "0.0.0.0:{TRAP_PORT}"',
            "  attributes = { service_name = \"alloy-snmptrap\" }",
            "  output { logs = [otelcol.processor.batch.out.input] }",
            "}",
            "",
            'otelcol.receiver.netflow "bench" {',
            '  scheme   = "netflow"',
            '  hostname = "0.0.0.0"',
            f"  port     = {FLOW_PORT}",
            "  output { logs = [otelcol.processor.batch.out.input] }",
            "}",
            "",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def docker_rm() -> None:
    subprocess.run(["docker", "rm", "-f", NAME], check=False, stdout=subprocess.DEVNULL)


def docker_run(cfg: Path, snmp_yml: Path) -> None:
    docker_rm()
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        NAME,
        "--network",
        "host",
        "--cpus=1",
        "-e",
        "GOMAXPROCS=1",
        "-v",
        f"{cfg}:/etc/alloy/config.alloy:ro",
        "-v",
        f"{snmp_yml}:/etc/alloy/snmp-network.yml:ro",
        IMAGE,
        "run",
        "/etc/alloy/config.alloy",
        "--server.http.listen-addr=127.0.0.1:19192",
        "--stability.level=experimental",
        "--storage.path=/tmp/alloy-bench",
        "--cluster.enabled=false",
    ]
    subprocess.run(cmd, check=True)
    for _ in range(40):
        try:
            fetch_metrics()
            return
        except OSError:
            time.sleep(0.5)
    logs = subprocess.check_output(["docker", "logs", NAME], stderr=subprocess.STDOUT, text=True)
    raise SystemExit("Alloy did not publish metrics:\n" + logs[-4000:])


def fetch_metrics() -> str:
    with urllib.request.urlopen(METRICS, timeout=5) as r:
        return r.read().decode("utf-8", errors="replace")


def metric_sum(text: str, prefix: str) -> float:
    total = 0.0
    for line in text.splitlines():
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        if "{" in line[: line.find(" ")] or line.startswith(prefix + " ") or line.startswith(prefix + "{"):
            try:
                total += float(line.rsplit(" ", 1)[1])
            except (IndexError, ValueError):
                pass
    return total


def metric_one(text: str, name: str) -> float:
    for line in text.splitlines():
        if not line.startswith(name):
            continue
        try:
            return float(line.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            continue
    return 0.0


def docker_stats() -> dict:
    fmt = "{{.CPUPerc}}\t{{.MemUsage}}"
    raw = subprocess.check_output(["docker", "stats", "--no-stream", "--format", fmt, NAME], text=True).strip()
    cpu_s, mem = (raw.split("\t") + ["", ""])[:2]
    cpu = float(cpu_s.replace("%", "").strip() or "0")
    rss = mem.split("/")[0].strip()
    return {"cpu_pct_docker": cpu, "mem_docker": rss}


# --- UDP lanes -------------------------------------------------------------


def syslog_msg(i: int) -> bytes:
    return (
        f"<189>Sep  9 16:00:00 sw-{(i % 100)+1:03d} "
        f"%LINK-3-UPDOWN: Interface GigabitEthernet1/0/{(i % 48)+1}, "
        f"changed state to up seq={i}\n"
    ).encode()


def trap_pkt(i: int) -> bytes:
    ifx = (i % 48) + 1
    extra = [encode_varbind((1, 3, 6, 1, 2, 1, 2, 2, 1, 1, ifx), 0x02, bytes([ifx]))]
    return encode_trap((1, 3, 6, 1, 6, 3, 1, 1, 5, 3), extra)


def _u16(n: int) -> bytes:
    return struct.pack("!H", n)


def _u32b(n: int) -> bytes:
    return struct.pack("!I", n)


def nf9_template() -> bytes:
    body = _u16(NF_TID) + _u16(len(NF_FIELDS))
    for ftype, flen in NF_FIELDS:
        body += _u16(ftype) + _u16(flen)
    raw = body + b"\x00" * ((-len(body)) % 4)
    return _u16(0) + _u16(4 + len(raw)) + raw


def nf9_data(seq: int, records: int) -> bytes:
    recs = b""
    for n in range(records):
        recs += (
            socket.inet_aton("203.0.113.10")
            + socket.inet_aton(f"203.0.113.{(n % 200) + 1}")
            + _u32b(1000)
            + _u32b(5000)
            + _u32b(1500)
            + _u32b(10)
            + _u16(1)
            + _u16(2)
            + _u16(10000 + (seq + n) % 50000)
            + _u16(443)
            + bytes((6, 0, 4, 0))
        )
    pad = recs + b"\x00" * ((-len(recs)) % 4)
    fs = _u16(NF_TID) + _u16(4 + len(pad)) + pad
    hdr = _u16(9) + _u16(1 + records) + _u32b(1_000_000) + _u32b(int(time.time())) + _u32b(seq) + _u32b(NF_SID)
    return hdr + fs


def blast(kind: str, eps: int, seconds: float) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    t0 = time.perf_counter()
    n = max(1, int(eps * seconds))
    recs_per_flow = 10
    port = {"syslog": SYSLOG_PORT, "traps": TRAP_PORT, "flow": FLOW_PORT}[kind]
    have_snmptrap = shutil.which("snmptrap")
    if kind == "flow":
        import runpy

        nf = runpy.run_path(str(ROOT / "scripts" / "send-flow-samples.py"))
        for i in range(n):
            sock.sendto(nf["build_case"]("nf9_clean", seq=i + 1), ("127.0.0.1", port))
            sent += 1
            tgt = t0 + (i + 1) * (seconds / n)
            delay = tgt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        sock.close()
        return sent
    for i in range(n):
        if kind == "syslog":
            sock.sendto(syslog_msg(i), ("127.0.0.1", port))
        elif kind == "traps":
            pkt = bytearray(_TRAP_TEMPLATE)
            pkt[17:21] = (i & 0xFFFFFFFF).to_bytes(4, "big")
            sock.sendto(bytes(pkt), ("127.0.0.1", port))
        sent += 1
        tgt = t0 + (i + 1) * (seconds / n)
        delay = tgt - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    sock.close()
    return sent


def _nf9_header_template() -> bytes:
    tmpl = nf9_template()
    hdr = _u16(9) + _u16(1) + _u32b(1_000_000) + _u32b(int(time.time())) + _u32b(0) + _u32b(NF_SID)
    return hdr + tmpl


def _nf9_full(seq: int, records: int) -> bytes:
    tmpl = nf9_template()
    data = nf9_data(seq + 1, records)
    # nf9_data already has a header; rebuild as template+data in one packet
    body = tmpl + data[20:]
    count = 1 + records
    hdr = _u16(9) + _u16(count) + _u32b(1_000_000) + _u32b(int(time.time())) + _u32b(seq) + _u32b(NF_SID)
    return hdr + body


def _sum_prefixed(text: str, prefix: str, needle: str | None = None) -> float:
    total = 0.0
    for line in text.splitlines():
        if not line.startswith(prefix) or line.startswith("#"):
            continue
        if needle and needle not in line:
            continue
        try:
            total += float(line.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            pass
    return total


def accepted_logs(text: str, needle: str | None = None) -> float:
    return _sum_prefixed(text, "otelcol_receiver_accepted_log_records", needle)


def refused_logs(text: str, needle: str | None = None) -> float:
    return _sum_prefixed(text, "otelcol_receiver_refused_log_records", needle)


# Captured from net-snmp `snmptrap -v 2c` (linkDown). Replay; bump request-id.
_TRAP_TEMPLATE = bytes.fromhex(
    "305502010104067075626c6963a748020452a7c433020100020100303a"
    "300f06082b060102010103004303029d8c3017060a2b0601060301010401"
    "0006092b0601060301010503300e06092b0601020102020101020101"
)


def ramp_lane(kind: str, eps_max: int, hold: float) -> dict:
    """Find highest EPS with <2% refuse and accepted ≈ sent."""
    results = []
    best = 0
    guess = min(int(os.environ.get("ALLOY_BENCH_EPS_START", "200")), eps_max)
    while guess <= eps_max:
        needle = {"syslog": "syslog", "traps": "snmptrap", "flow": "netflow"}[kind]
        before = fetch_metrics()
        a0, r0 = accepted_logs(before, needle), refused_logs(before, needle)
        sent = blast(kind, guess, hold)
        time.sleep(1.5)
        after = fetch_metrics()
        a1, r1 = accepted_logs(after, needle), refused_logs(after, needle)
        got = a1 - a0
        drop = r1 - r0
        ok = sent > 0 and got >= sent * 0.90 and drop <= sent * 0.05
        row = {
            "target_eps": guess,
            "sent": sent,
            "accepted_delta": got,
            "refused_delta": drop,
            "ok": ok,
            **docker_stats(),
            "rss_bytes": metric_one(after, "process_resident_memory_bytes"),
            "cpu_seconds": metric_one(after, "process_cpu_seconds_total"),
        }
        results.append(row)
        rec = [ln for ln in after.splitlines() if ln.startswith("otelcol_receiver_") and "bucket" not in ln][:8]
        print(f"  {kind} {guess} eps  sent={sent} accepted={got:.0f} refused={drop:.0f} ok={ok}")
        if rec:
            print("   ", rec[0][:140])
        if ok:
            best = guess
            guess = guess * 2 if guess * 2 <= eps_max else eps_max + 1
            if guess == best:
                break
        else:
            break
    return {"lane": kind, "best_eps": best, "points": results}


# --- SNMP phase ------------------------------------------------------------


def run_snmp(out: Path, devices: int, ports: int, settle: float) -> dict:
    farm = SnmpFarm(devices, ports)
    farm.start()
    write_alloy(out / "config.alloy", devices, "snmp")
    docker_run(out / "config.alloy", out / "snmp.yml")
    t0 = time.time()
    samples: list[float] = []

    def _sample() -> None:
        while time.time() - t0 < settle + 12:
            try:
                samples.append(docker_stats()["cpu_pct_docker"])
            except Exception:
                pass
            time.sleep(1)

    threading.Thread(target=_sample, daemon=True).start()
    time.sleep(8)
    m1 = fetch_metrics()
    time.sleep(max(settle, 40))
    m2 = fetch_metrics()
    stats = docker_stats()
    if samples:
        stats["cpu_pct_docker_max"] = max(samples)
        stats["cpu_pct_docker_mean"] = round(sum(samples) / len(samples), 2)
        # docker --cpus=1 reports % of one host CPU; cap the fraction at 1.
        stats["cpu_core_fraction_peak"] = round(min(max(samples) / 100.0, 1.0), 3)
    cpu0 = metric_one(m1, "process_cpu_seconds_total")
    cpu1 = metric_one(m2, "process_cpu_seconds_total")
    wall = max(time.time() - t0 - 8, 1)
    cpu_frac = (cpu1 - cpu0) / wall
    peak = stats.get("cpu_core_fraction_peak") or cpu_frac
    scrape_n = metric_one(m2, "net_conntrack_dialer_conn_established_total{dialer_name=\"prometheus.scrape.hot\"")
    rss = metric_one(m2, "process_resident_memory_bytes")
    if not os.environ.get("ALLOY_BENCH_KEEP"):
        farm.stop()
        docker_rm()
    ifaces = devices * ports
    return {
        "devices": devices,
        "ports_per_device": ports,
        "interfaces": ifaces,
        "cpu_core_fraction_avg": round(cpu_frac, 3),
        "cpu_core_fraction_peak": peak,
        "devices_per_core": round(devices / max(peak, 0.02), 0),
        "interfaces_per_core": round(ifaces / max(peak, 0.02), 0),
        "rss_bytes": rss,
        "rss_mib_per_device": round((rss / 1024 / 1024) / max(devices, 1), 2),
        "devices_per_gib": round(devices / max(rss / 1024 / 1024 / 1024, 0.08), 0),
        "hot_scrapes_established": scrape_n,
        **stats,
        "note": "localhost IF-MIB+device_base hot / if_mib_meta cold; no device timeout",
    }


def run_events(out: Path, eps_max: int, hold: float) -> list[dict]:
    write_alloy(out / "config.alloy", 0, "events")
    docker_run(out / "config.alloy", out / "snmp.yml")
    time.sleep(3)
    rows = []
    for kind in ("syslog", "traps", "flow"):
        print(f"==> ramp {kind}")
        rows.append(ramp_lane(kind, eps_max, hold))
        time.sleep(1)
    docker_rm()
    return rows


def render_md(report: dict) -> str:
    snmp = report.get("snmp") or {}
    ev = {r["lane"]: r for r in report.get("events") or []}
    lines = [
        "# Alloy scale bench",
        "",
        f"Image `{report.get('image')}` · 1 CPU (`GOMAXPROCS=1`) · {report.get('when')}",
        "",
        "## SNMP (48-port campus switch stand-in)",
        "",
        f"- Devices: **{snmp.get('devices')}** × **{snmp.get('ports_per_device')}** ports "
        f"= {snmp.get('interfaces')} interfaces",
        f"- CPU while polling: peak **{snmp.get('cpu_core_fraction_peak')}** of one core "
        f"(avg {snmp.get('cpu_core_fraction_avg')})",
        f"- Rule of thumb from this run: **~{snmp.get('devices_per_core')} devices / core** "
        f"or **~{snmp.get('interfaces_per_core')} interfaces / core**",
        f"- RSS: {snmp.get('rss_bytes')} bytes "
        f"(~{snmp.get('rss_mib_per_device')} MiB/device, ~{snmp.get('devices_per_gib')} devices / GiB)",
        f"- Docker stats: peak {snmp.get('cpu_pct_docker_max')}% · {snmp.get('mem_docker')}",
        f"- Hot scrape TCP sessions: {snmp.get('hot_scrapes_established')}",
        "",
        "Simulator answers on localhost with no timeout. Real gear that sits on "
        "`timeout_ms` eats the budget faster. Chassis / wireless controllers with "
        "thousands of ifIndex rows look like many of these 48-port boxes.",
        "",
        "## Events per second (one core, decode + OTLP HTTP)",
        "",
        "| Lane | Best sustained EPS | What an event is |",
        "|------|--------------------|------------------|",
    ]
    for lane, label in (("syslog", "one syslog datagram"), ("traps", "one SNMPv2c trap"), ("flow", "one NetFlow v9 record")):
        best = (ev.get(lane) or {}).get("best_eps", "—")
        lines.append(f"| {lane} | **{best}** | {label} |")
    lines += [
        "",
        "Ramp doubles the offer until accepted < 95% of sent or refuses appear. "
        "That is a **lab ceiling**, not an SLA — leave half for a noisy day and Cloud export.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/alloy-scale-bench")
    ap.add_argument("--devices", type=int, default=100)
    ap.add_argument("--ports", type=int, default=48)
    ap.add_argument("--snmp-settle", type=float, default=80)
    ap.add_argument("--eps-max", type=int, default=8000)
    ap.add_argument("--eps-hold", type=float, default=8)
    ap.add_argument("--eps-start", type=int, default=200)
    ap.add_argument("--skip-snmp", action="store_true")
    ap.add_argument("--skip-events", action="store_true")
    ap.add_argument("--keep", action="store_true", help="leave Alloy + SNMP farm running")
    args = ap.parse_args()
    if args.keep:
        os.environ["ALLOY_BENCH_KEEP"] = "1"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    merge_snmp_yml(out / "snmp.yml")

    report = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "image": IMAGE,
        "gomaxprocs": 1,
        "devices_requested": args.devices,
        "ports": args.ports,
    }
    sink = start_sink()
    try:
        if not args.skip_snmp:
            print(f"==> SNMP {args.devices} × {args.ports}")
            report["snmp"] = run_snmp(out, args.devices, args.ports, args.snmp_settle)
            print(json.dumps(report["snmp"], indent=2))
        if not args.skip_events:
            print("==> event lanes")
            os.environ["ALLOY_BENCH_EPS_START"] = str(args.eps_start)
            report["events"] = run_events(out, args.eps_max, args.eps_hold)
    finally:
        if not args.keep:
            docker_rm()
            sink.shutdown()

    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_md(report), encoding="utf-8")
    dest = ROOT / "fixtures/alloy-scale-bench"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(out / "report.json", dest / "report.json")
    shutil.copy(out / "report.md", dest / "report.md")
    print(f"wrote {out / 'report.md'} and {dest / 'report.md'}")
    if args.keep:
        print("ALLOY_BENCH_KEEP: farm + container still up (Ctrl-C to stop)")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            docker_rm()
    return 0


if __name__ == "__main__":
    sys.exit(main())
