#!/usr/bin/env python3
"""Verify snmp_group label on marcnetterfield1 / configured Grafana stack."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

base = os.environ.get("GRAFANA_URL", "").rstrip("/")
token = os.environ.get("GRAFANA_TOKEN", "")
if not base or not token:
    sys.exit("set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

req = urllib.request.Request(
    f"{base}/api/datasources",
    headers={"Authorization": f"Bearer {token}"},
)
ds = json.load(urllib.request.urlopen(req, timeout=30))
prom = next(d for d in ds if d.get("type") == "prometheus")
uid = prom["uid"]
print(f"using prometheus datasource: {prom.get('name')} uid={uid}")


def query(expr: str, *, range_query: bool = False) -> list:
    q = {
        "refId": "A",
        "expr": expr,
        "datasource": {"type": "prometheus", "uid": uid},
    }
    if range_query:
        q.update({"range": True, "instant": False})
    else:
        q.update({"instant": True})
    body = json.dumps({"queries": [q], "from": "now-30m", "to": "now"}).encode()
    req = urllib.request.Request(
        f"{base}/api/ds/query",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    resp = json.load(urllib.request.urlopen(req, timeout=60))
    frames = resp.get("results", {}).get("A", {}).get("frames", [])
    if not frames:
        return []
    return frames[0].get("data", {}).get("values", [])


queries = [
    "count by (snmp_group) (kentik_snmp_PollingHealth)",
    "count by (snmp_group, device_name) (kentik_snmp_PollingHealth)",
]
for q in queries:
    print(f"\n{q}")
    try:
        vals = query(q)
        print(" ", vals if vals else "(no data)")
        if not vals and "kentik" in q:
            vals = query(q, range_query=True)
            if vals:
                print("  (range 6h)", vals[:2], "...")
    except urllib.error.HTTPError as e:
        print("  HTTP", e.code, e.read().decode()[:200])
