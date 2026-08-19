#!/usr/bin/env python3
"""Craft NetFlow v9 / IPFIX UDP samples and send them to a collector.

Used to probe pktvisor's flow parser (colocated :19995) without depending on
softflowd. Distinctive TEST-NET-3 5-tuples + unique source_id values so we do
not clobber softflowd's global (source_id, template_id) map inside pktvisor.

Cases:
  nf9_clean          template + data (no options) — should parse
  nf9_with_options   softflowd-like: options data flowset 256 before real data
  ipfix_clean        IPFIX set 2 + data
  ipfix_with_options options set 3 + options data 256 + data

Examples:
  python3 send-flow-samples.py --dump
  python3 send-flow-samples.py --host 127.0.0.1 --port 19995 --probe
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import time
import urllib.error
import urllib.request
from typing import Iterable

# IANA IPFIX / NetFlow v9 information elements used in the probe record.
# Lengths match pktvisor's NFSample::Flows (INPUT_SNMP is uint16, not 4-byte).
FIELDS: list[tuple[int, int]] = [
    (8, 4),  # IPV4_SRC
    (12, 4),  # IPV4_DST
    (22, 4),  # FIRST_SWITCHED
    (21, 4),  # LAST_SWITCHED
    (1, 4),  # IN_BYTES
    (2, 4),  # IN_PKTS
    (10, 2),  # INPUT_SNMP
    (14, 2),  # OUTPUT_SNMP
    (7, 2),  # L4_SRC_PORT
    (11, 2),  # L4_DST_PORT
    (4, 1),  # PROTOCOL
    (6, 1),  # TCP_FLAGS
    (60, 1),  # IP_PROTOCOL_VERSION
    (5, 1),  # TOS
]

SRC = "203.0.113.10"
DST = "203.0.113.20"
SPORT, DPORT = 12345, 8080
IN_BYTES = 5_000_000
IN_PKTS = 1000
RECORD_LEN = sum(length for _, length in FIELDS)

# Unique exporter IDs so probe templates never overwrite softflowd (sid=0).
SID = {
    "nf9_clean": 0x9001,
    "nf9_with_options": 0x9002,
    "ipfix_clean": 0x9003,
    "ipfix_with_options": 0x9004,
}
TID_DATA = 3000
TID_OPTIONS = 256  # first legal data template id — pktvisor treats this as data


def u16(n: int) -> bytes:
    return struct.pack("!H", n)


def u32(n: int) -> bytes:
    return struct.pack("!I", n)


def pad4(raw: bytes) -> bytes:
    return raw + b"\x00" * ((-len(raw)) % 4)


def flowset(fsid: int, body: bytes) -> bytes:
    raw = pad4(u16(fsid) + u16(0) + body)
    return u16(fsid) + u16(len(raw)) + raw[4:]


def template_body(tid: int, fields: Iterable[tuple[int, int]]) -> bytes:
    fields = list(fields)
    body = u16(tid) + u16(len(fields))
    for ftype, flen in fields:
        body += u16(ftype) + u16(flen)
    return body


def data_record() -> bytes:
    rec = (
        socket.inet_aton(SRC)
        + socket.inet_aton(DST)
        + u32(1000)
        + u32(5000)
        + u32(IN_BYTES)
        + u32(IN_PKTS)
        + u16(1)
        + u16(2)
        + u16(SPORT)
        + u16(DPORT)
        + bytes((17, 0, 4, 0))
    )
    if len(rec) != RECORD_LEN:
        raise RuntimeError(f"record {len(rec)} != {RECORD_LEN}")
    return rec


def options_template_v9() -> bytes:
    """Minimal Cisco-style options template (flowset 1), template id 256."""
    # scope: 1 field (4 bytes), options: 2 fields (8 bytes) → body 6+4+8=18, fs=22
    body = u16(TID_OPTIONS) + u16(4) + u16(8)
    body += u16(1) + u16(4)  # scope: System
    body += u16(48) + u16(4)  # Flow sampler random interval (placeholder)
    body += u16(49) + u16(4)
    return flowset(1, body)


def options_data() -> bytes:
    return flowset(TID_OPTIONS, b"\x00" * 16)


def nf9_packet(source_id: int, sets: list[bytes], seq: int, count: int) -> bytes:
    hdr = u16(9) + u16(count) + u32(1_000_000) + u32(int(time.time())) + u32(seq) + u32(source_id)
    return hdr + b"".join(sets)


def ipfix_packet(odid: int, sets: list[bytes], seq: int) -> bytes:
    body = b"".join(sets)
    return u16(10) + u16(16 + len(body)) + u32(int(time.time())) + u32(seq) + u32(odid) + body


def build_case(name: str, seq: int = 1) -> bytes:
    rec = data_record()
    if name == "nf9_clean":
        sets = [flowset(0, template_body(TID_DATA, FIELDS)), flowset(TID_DATA, rec)]
        return nf9_packet(SID[name], sets, seq, count=2)
    if name == "nf9_with_options":
        sets = [
            flowset(0, template_body(TID_DATA, FIELDS)),
            options_template_v9(),
            options_data(),
            flowset(TID_DATA, rec),
        ]
        return nf9_packet(SID[name], sets, seq, count=4)
    if name == "ipfix_clean":
        sets = [flowset(2, template_body(TID_DATA, FIELDS)), flowset(TID_DATA, rec)]
        return ipfix_packet(SID[name], sets, seq)
    if name == "ipfix_with_options":
        # IPFIX options template = set 3 (pktvisor skips); options data id 256.
        opt_tmpl = template_body(TID_OPTIONS, [(1, 4), (48, 4)])
        sets = [
            flowset(2, template_body(TID_DATA, FIELDS)),
            flowset(3, opt_tmpl),
            options_data(),
            flowset(TID_DATA, rec),
        ]
        return ipfix_packet(SID[name], sets, seq)
    raise SystemExit(f"unknown case {name}")


CASES = ("nf9_clean", "nf9_with_options", "ipfix_clean", "ipfix_with_options")


def pktvisor_snapshot(base: str) -> dict:
    out: dict = {"ok": False}
    try:
        with urllib.request.urlopen(base + "/api/v1/policies", timeout=5) as r:
            policies = json.load(r)
        out["ok"] = True
        errors = {}
        for name, body in policies.items():
            inp = (body or {}).get("input") or {}
            for _mod, rec in inp.items():
                flow = (rec or {}).get("flow") or {}
                if "packet_errors" in flow:
                    errors[name] = flow["packet_errors"]
        out["packet_errors"] = errors
        out["netflow_errors"] = errors.get("lab_netflow_summary")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        out["error"] = str(e)
    try:
        url = base + "/api/v1/policies/lab_netflow_summary/metrics/bucket/1"
        with urllib.request.urlopen(url, timeout=5) as r:
            raw = r.read().decode("utf-8", errors="replace")
        out["bucket1"] = raw[:4000]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        out["bucket1"] = f"err:{e}"
    try:
        url = base + "/api/v1/policies/__all/metrics/prometheus"
        with urllib.request.urlopen(url, timeout=5) as r:
            lines = r.read().decode("utf-8", errors="replace").splitlines()
        keep = [
            ln
            for ln in lines
            if ln.startswith("flow_")
            and any(x in ln for x in ("in_bytes", "records_flows", "203.0.113", "127.0.0.1"))
        ]
        out["prom"] = keep[:40]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        out["prom"] = [f"err:{e}"]
    return out


def send_udp(host: str, port: int, payload: bytes, copies: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for i in range(copies):
            sock.sendto(payload if i == 0 else build_case_from_payload(payload, i + 1), (host, port))
    finally:
        sock.close()


def build_case_from_payload(first: bytes, seq: int) -> bytes:
    """Rebuild with a new sequence so pktvisor does not see identical PDUs."""
    ver = struct.unpack_from("!H", first, 0)[0]
    if ver == 9:
        name = {
            SID["nf9_clean"]: "nf9_clean",
            SID["nf9_with_options"]: "nf9_with_options",
        }.get(struct.unpack_from("!I", first, 16)[0])
        if name:
            return build_case(name, seq=seq)
    elif ver == 10:
        name = {
            SID["ipfix_clean"]: "ipfix_clean",
            SID["ipfix_with_options"]: "ipfix_with_options",
        }.get(struct.unpack_from("!I", first, 12)[0])
        if name:
            return build_case(name, seq=seq)
    return first


def probe(host: str, port: int, api: str, copies: int, wait_s: int) -> dict:
    report: dict = {"target": f"{host}:{port}", "copies": copies, "cases": {}}
    before = pktvisor_snapshot(api)
    report["before"] = before
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for name in CASES:
            payload = build_case(name, seq=1)
            err0 = pktvisor_snapshot(api).get("netflow_errors")
            t0 = time.time()
            for i in range(copies):
                sock.sendto(build_case(name, seq=i + 1), (host, port))
            time.sleep(0.4)
            snap = pktvisor_snapshot(api)
            err1 = snap.get("netflow_errors")
            delta = None
            if isinstance(err0, int) and isinstance(err1, int):
                delta = err1 - err0
            report["cases"][name] = {
                "bytes": len(payload),
                "errors_before": err0,
                "errors_after": err1,
                "error_delta": delta,
                "elapsed_s": round(time.time() - t0, 3),
                "verdict": (
                    "PARSE_FAIL"
                    if isinstance(delta, int) and delta >= max(1, int(copies * 0.8))
                    else "PARSE_OK"
                    if isinstance(delta, int) and delta <= 2
                    else "MIXED"
                ),
            }
    finally:
        sock.close()

    if wait_s > 0:
        print(f"==> wait {wait_s}s for pktvisor 60s bucket", flush=True)
        time.sleep(wait_s)
    report["after"] = pktvisor_snapshot(api)
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=19995)
    p.add_argument("--api", default="http://127.0.0.1:10853")
    p.add_argument("--copies", type=int, default=20)
    p.add_argument("--wait", type=int, default=70, help="seconds to wait for bucket/1 after sends")
    p.add_argument("--dump", action="store_true", help="print sizes/hex, do not send")
    p.add_argument("--probe", action="store_true", help="send all cases and read pktvisor errors")
    p.add_argument("--case", choices=CASES, help="send a single case (no API probe)")
    args = p.parse_args()

    if args.dump:
        for name in CASES:
            pkt = build_case(name)
            print(f"{name} len={len(pkt)} sid={SID[name]} hex={pkt[:48].hex()}")
        return 0

    if args.probe:
        report = probe(args.host, args.port, args.api.rstrip("/"), args.copies, args.wait)
        print(json.dumps(report, indent=2))
        return 0

    name = args.case or "nf9_clean"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for i in range(args.copies):
            sock.sendto(build_case(name, seq=i + 1), (args.host, args.port))
    finally:
        sock.close()
    print(f"sent {args.copies}x {name} -> {args.host}:{args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
