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
hdr = {"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"}

for uid in ["mah4cjt", "net-o11y-bgp-status", "net-o11y-topology", "net-o11y-device-details"]:
    req = urllib.request.Request(f"{base}/api/dashboards/uid/{uid}", headers=hdr)
    with urllib.request.urlopen(req, timeout=60) as r:
        dash = json.load(r)["dashboard"]
    blob = json.dumps(dash)
    print(
        uid,
        "srl_bgp=",
        blob.count("srl_bgp_neighbor"),
        "gnmi_bgp=",
        blob.count("gnmi_bgp_neighbors"),
    )
    print(" ", f"{base}/d/{uid}")
    for t in dash.get("templating", {}).get("list", []):
        q = t.get("query")
        d = t.get("definition")
        qs = q if isinstance(q, str) else json.dumps(q)
        ds = d if isinstance(d, str) else (json.dumps(d) if d is not None else "")
        joined = (qs or "") + (ds or "")
        if "bgp" in joined.lower() or "gnmi_bgp" in joined:
            print(f"  var {t.get('name')}: {qs[:160]}")
