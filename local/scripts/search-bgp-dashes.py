#!/usr/bin/env python3
"""Search Grafana dashboards relevant to BGP."""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

env = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

base = env["GRAFANA_URL"].rstrip("/")
hdr = {"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"}


def get(path, params=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


for q in ["bgp", "Netterfield", "net-o11y", "Network O11y"]:
    hits = get("/api/search", {"query": q, "type": "dash-db"})
    print(f"=== {q} ({len(hits)}) ===")
    for d in hits[:30]:
        print(f"  {d.get('uid'):32} {d.get('title')}")

# direct uid lookups
for uid in ["mah4cjt", "net-o11y-bgp-status", "net-o11y-topology", "net-o11y-device-details"]:
    try:
        d = get(f"/api/dashboards/uid/{uid}")
        print(f"UID {uid}: {d['dashboard'].get('title')}")
    except Exception as e:
        print(f"UID {uid}: missing ({e})")
