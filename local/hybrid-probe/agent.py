#!/usr/bin/env python3
"""Hybrid mesh probe agent — HTTP/TCP checks with OTLP export to Grafana Cloud.

Usage:
  pip install -r local/hybrid-probe/requirements.txt --ignore-scripts
  python local/hybrid-probe/agent.py --config local/hybrid-probe/targets-laptop.yaml
  python local/hybrid-probe/agent.py --config local/hybrid-probe/targets-aws.yaml --listen 18080

Metrics:
  hybrid_probe_success (1=ok)
  hybrid_probe_latency_ms
  hybrid_probe_up (agent heartbeat)
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from otel_push import load_otlp_env, push_gauge

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise SystemExit("pip install pyyaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def probe_http(url: str, timeout: float = 5.0) -> tuple[bool, float, str]:
    start = time.perf_counter()
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "network-o11y-hybrid-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            _ = resp.read(256)
            if resp.status >= 400:
                return False, (time.perf_counter() - start) * 1000, f"http_{resp.status}"
            return True, (time.perf_counter() - start) * 1000, "ok"
    except urllib.error.HTTPError as e:
        # ALB with no listener may return 4xx but proves L3/L4 path
        if e.code in (301, 302, 403, 404, 503):
            return True, (time.perf_counter() - start) * 1000, f"http_{e.code}"
        return False, (time.perf_counter() - start) * 1000, f"http_{e.code}"
    except Exception as e:
        return False, (time.perf_counter() - start) * 1000, type(e).__name__


def probe_tcp(host: str, port: int, timeout: float = 3.0) -> tuple[bool, float, str]:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, (time.perf_counter() - start) * 1000, "ok"
    except Exception as e:
        return False, (time.perf_counter() - start) * 1000, type(e).__name__


def run_probe(target: dict[str, Any]) -> tuple[bool, float, str]:
    kind = target.get("kind", "http")
    if kind == "tcp":
        host = target["host"]
        port = int(target.get("port", 80))
        return probe_tcp(host, port, float(target.get("timeout_sec", 3)))
    url = target["url"]
    return probe_http(url, float(target.get("timeout_sec", 5)))


def emit(agent_id: str, region: str, target: dict[str, Any], ok: bool, ms: float) -> None:
    labels = {
        "agent_id": agent_id,
        "region": region,
        "target": target.get("name", "unknown"),
        "target_type": target.get("type", "aws"),
        "direction": target.get("direction", "outbound"),
    }
    push_gauge("hybrid_probe_success", 1.0 if ok else 0.0, labels)
    push_gauge("hybrid_probe_latency_ms", ms, labels)


def probe_loop(cfg: dict[str, Any]) -> None:
    agent_id = str(cfg.get("agent_id", "unknown"))
    region = str(cfg.get("region", "local"))
    interval = float(cfg.get("interval_sec", 30))
    targets: list[dict[str, Any]] = list(cfg.get("targets") or [])
    print(f"probe agent={agent_id} region={region} targets={len(targets)} interval={interval}s")
    while True:
        push_gauge("hybrid_probe_up", 1.0, {"agent_id": agent_id, "region": region})
        for t in targets:
            ok, ms, reason = run_probe(t)
            emit(agent_id, region, t, ok, ms)
            status = "OK" if ok else "FAIL"
            print(f"  [{status}] {t.get('name')}: {ms:.0f}ms ({reason})")
        time.sleep(interval)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def serve(port: int) -> None:
    srv = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"callback listener on 0.0.0.0:{port}")
    srv.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="targets YAML")
    parser.add_argument("--listen", type=int, default=0, help="callback HTTP port (AWS→laptop)")
    args = parser.parse_args()

    load_otlp_env()
    cfg = load_yaml(Path(args.config))

    if args.listen > 0:
        t = threading.Thread(target=serve, args=(args.listen,), daemon=True)
        t.start()

    try:
        probe_loop(cfg)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
