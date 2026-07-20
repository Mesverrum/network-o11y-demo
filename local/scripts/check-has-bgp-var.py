#!/usr/bin/env python3
import json
import urllib.request
from pathlib import Path

env = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

base = env["GRAFANA_URL"].rstrip("/")
req = urllib.request.Request(
    f"{base}/api/dashboards/uid/mah4cjt",
    headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"},
)
with urllib.request.urlopen(req, timeout=60) as r:
    dash = json.load(r)["dashboard"]

for t in dash.get("templating", {}).get("list", []):
    if t.get("name") == "has_bgp":
        print(json.dumps(t.get("query"), indent=2))
        print("definition:", t.get("definition"))
