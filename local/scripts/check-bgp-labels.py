#!/usr/bin/env python3
import json, urllib.parse, urllib.request
from pathlib import Path

env = {}
for line in (Path(".env").read_text().splitlines()):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

def pq(expr):
    q = urllib.parse.urlencode({"query": expr})
    url = (
        f"{env['GRAFANA_URL'].rstrip('/')}"
        f"/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

# Sample one BGP series labels
d = pq(
    '{__name__="gnmi_bgp_neighbors_srl_nokia_network_instance:network_instance_protocols_srl_nokia_bgp:bgp_neighbor_session_state"}'
)
print("session_state series:", len(d["data"]["result"]))
if d["data"]["result"]:
    print("labels:", json.dumps(d["data"]["result"][0]["metric"], indent=2))
    print("value:", d["data"]["result"][0]["value"][1])

print("\nsrl_bgp_* count:", pq('count({__name__=~"srl_bgp_.*"})')["data"]["result"])
print("job integrations/gnmi:", pq('count({job="integrations/gnmi"})')["data"]["result"])
