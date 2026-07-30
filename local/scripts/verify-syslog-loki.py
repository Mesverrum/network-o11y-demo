#!/usr/bin/env python3
"""Quick Loki check for device syslog lines on the operator stack."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

url = env.get("GRAFANA_URL", "").rstrip("/")
token = env.get("GRAFANA_TOKEN", "")
loki_uid = env.get("GRAFANA_LOKI_UID", "grafanacloud-logs")
if not url or not token:
    print("GRAFANA_URL/GRAFANA_TOKEN required in local/.env", file=sys.stderr)
    sys.exit(1)

queries = [
    '{service_name=~"ktranslate.*"} | json | instrumentation_name="ktranslate-syslog"',
    '{service_name=~"ktranslate-syslog.*"}',
    '{service_name=~"ktranslate.*"} | json | eventType="KSnmpTrap"',
]
start = str(int((time.time() - 3600) * 1e9))
for q in queries:
    params = urllib.parse.urlencode({"query": q, "limit": "5", "start": start})
    req = urllib.request.Request(
        f"{url}/api/datasources/proxy/uid/{loki_uid}/loki/api/v1/query_range?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = json.load(urllib.request.urlopen(req, timeout=30))
    streams = data.get("data", {}).get("result", [])
    lines = sum(len(s.get("values", [])) for s in streams)
    print(f"query={q!r} streams={len(streams)} lines={lines}")
    for s in streams[:2]:
        for _ts, line in s.get("values", [])[:1]:
            print(" sample:", line[:240])
