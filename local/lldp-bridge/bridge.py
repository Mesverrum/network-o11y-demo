#!/usr/bin/env python3
"""
lldp-bridge — emit network_topology_edge_info from SR Linux LLDP via sr_cli.

Nokia SR Linux does not expose IEEE LLDP-MIB over SNMP, so grafana/network-topology-
exporter cannot discover edges. This sidecar reads LLDP neighbors with
`sr_cli` (docker exec) and exposes Prometheus metrics Alloy scrapes.

Labels match network-topology-exporter so the topology-graph dashboard works.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

NODES = [n.strip() for n in os.environ.get("LLDP_NODES", "spine1,leaf1,leaf2").split(",") if n.strip()]
INTERVAL = int(os.environ.get("LLDP_INTERVAL_SEC", "60"))
LISTEN = os.environ.get("LLDP_LISTEN", "0.0.0.0:9101")
TESTER_ID = os.environ.get("TESTER_ID", "network-lab")

IFACE_RE = re.compile(r"interface\s+(\S+)\s*\{")
NEIGH_RE = re.compile(r"neighbor\s+\S+\s*\{")
SYSNAME_RE = re.compile(r"system-name\s+(\S+)")
PORT_RE = re.compile(r"port-id\s+(\S+)")

_lock = threading.Lock()
_edges: set[tuple[str, str, str, str]] = set()
_last_ok = 0.0
_last_error = ""


def _sr_cli(node: str, cmd: str) -> str:
    return subprocess.check_output(
        ["docker", "exec", node, "sr_cli", "-d", cmd],
        text=True,
        stderr=subprocess.STDOUT,
        timeout=30,
    )


def _parse_neighbors(local: str, text: str) -> set[tuple[str, str, str, str]]:
    edges: set[tuple[str, str, str, str]] = set()
    iface = None
    in_neigh = False
    remote = None
    rport = None
    for line in text.splitlines():
        s = line.strip()
        m = IFACE_RE.search(s)
        if m:
            iface = m.group(1)
            in_neigh = False
            continue
        if NEIGH_RE.search(s):
            in_neigh = True
            remote = None
            rport = None
            continue
        if in_neigh and s == "}":
            if iface and remote and rport:
                edges.add((local, iface, remote, rport))
            in_neigh = False
            continue
        if not in_neigh:
            continue
        m = SYSNAME_RE.search(s)
        if m:
            remote = m.group(1)
            continue
        m = PORT_RE.search(s)
        if m:
            rport = m.group(1)
            continue
    return edges


def poll_once() -> None:
    global _edges, _last_ok, _last_error
    collected: set[tuple[str, str, str, str]] = set()
    errors: list[str] = []
    for node in NODES:
        try:
            out = _sr_cli(node, "info from state system lldp interface * neighbor *")
            collected |= _parse_neighbors(node, out)
        except Exception as exc:  # noqa: BLE001 — surface any poll failure
            errors.append(f"{node}: {exc}")
    with _lock:
        _edges = collected
        _last_ok = time.time()
        _last_error = "; ".join(errors)


def _prom_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_metrics() -> bytes:
    with _lock:
        edges = sorted(_edges)
        last_ok = _last_ok
        last_error = _last_error
    lines = [
        "# HELP network_topology_edge_info Topology edge discovered via LLDP (sr_cli bridge).",
        "# TYPE network_topology_edge_info gauge",
    ]
    for src, sport, dst, dport in edges:
        labels = (
            f'src_device="{_prom_escape(src)}",src_port="{_prom_escape(sport)}",'
            f'dst_device="{_prom_escape(dst)}",dst_port="{_prom_escape(dport)}",'
            f'discovery_proto="lldp",link_kind="ethernet",direction="forward",'
            f'tester_id="{_prom_escape(TESTER_ID)}"'
        )
        lines.append(f"network_topology_edge_info{{{labels}}} 1")
    lines.extend(
        [
            "# HELP lldp_bridge_edges Total unidirectional LLDP edges last poll.",
            "# TYPE lldp_bridge_edges gauge",
            f"lldp_bridge_edges{{tester_id=\"{_prom_escape(TESTER_ID)}\"}} {len(edges)}",
            "# HELP lldp_bridge_last_success_timestamp_seconds Unix time of last successful poll.",
            "# TYPE lldp_bridge_last_success_timestamp_seconds gauge",
            f"lldp_bridge_last_success_timestamp_seconds {last_ok if last_ok else 0}",
            "# HELP lldp_bridge_up 1 if last poll had no per-node errors.",
            "# TYPE lldp_bridge_up gauge",
            f'lldp_bridge_up{{tester_id="{_prom_escape(TESTER_ID)}"}} {0 if last_error else 1}',
        ]
    )
    if last_error:
        lines.append(f"# last_error {last_error}")
    return ("\n".join(lines) + "\n").encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        body = render_metrics()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def poll_loop() -> None:
    while True:
        poll_once()
        time.sleep(INTERVAL)


def main() -> None:
    host, _, port_s = LISTEN.partition(":")
    port = int(port_s or "9101")
    poll_once()
    threading.Thread(target=poll_loop, daemon=True).start()
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
