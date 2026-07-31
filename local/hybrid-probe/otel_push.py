"""Minimal OTLP/HTTP gauge push to Grafana Cloud (no full SDK)."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ENV: dict[str, str] | None = None
_SEQ = 0


def load_otlp_env() -> dict[str, str]:
    global _ENV
    if _ENV is not None:
        return _ENV
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("GC_OTLP_URL", "GC_OTLP_ACCOUNT", "GC_OTLP_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    missing = [k for k in ("GC_OTLP_URL", "GC_OTLP_ACCOUNT", "GC_OTLP_KEY") if not env.get(k)]
    if missing:
        raise RuntimeError(f"Missing OTLP creds: {missing} (set in local/.env)")
    _ENV = env
    return env


def push_gauge(name: str, value: float, labels: dict[str, str]) -> None:
    global _SEQ
    env = load_otlp_env()
    _SEQ += 1
    now_ns = int(time.time() * 1_000_000_000)
    attrs = [{"key": k, "value": {"stringValue": v}} for k, v in sorted(labels.items())]
    payload = {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "hybrid-probe"}},
                        {"key": "service.namespace", "value": {"stringValue": "network-o11y-demo"}},
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "hybrid-probe"},
                        "metrics": [
                            {
                                "name": name,
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "attributes": attrs,
                                            "timeUnixNano": str(now_ns),
                                            "asDouble": value,
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    url = env["GC_OTLP_URL"].rstrip("/") + "/v1/metrics"
    auth = base64.b64encode(f"{env['GC_OTLP_ACCOUNT']}:{env['GC_OTLP_KEY']}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as e:
        print(f"OTLP push failed for {name}: {e}", file=__import__("sys").stderr)
