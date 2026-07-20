#!/usr/bin/env python3
"""Verify rewritten BGP PromQL returns data."""
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
P = (
    "gnmi_bgp_neighbors_srl_nokia_network_instance:"
    "network_instance_protocols_srl_nokia_bgp:bgp_neighbor_"
)


def pq(q):
    url = (
        base
        + "/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?"
        + urllib.parse.urlencode({"query": q})
    )
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


queries = {
    "sessions": f'count({{__name__="{P}established_transitions", job="gnmic"}})',
    "up": f'count({{__name__="{P}established_transitions", job="gnmic"}} >= 1)',
    "rx_routes": f'sum({{__name__="{P}afi_safi_received_routes", job="gnmic", afi_safi_afi_safi_name="ipv4-unicast"}})',
    "act_routes": f'sum({{__name__="{P}afi_safi_active_routes", job="gnmic", afi_safi_afi_safi_name="ipv4-unicast"}})',
    "overlay_peers": f'count({{__name__="{P}established_transitions", job="gnmic", neighbor_peer_address=~"10[.].*"}})',
    "underlay_192": f'count({{__name__="{P}established_transitions", job="gnmic", neighbor_peer_address=~"192[.]168[.].*"}}) or vector(0)',
    "devices": f'count(count by (source) ({{__name__="{P}established_transitions", job="gnmic"}}))',
}

for name, q in queries.items():
    res = pq(q)["data"]["result"]
    val = res[0]["value"][1] if res else "empty"
    print(f"{name:16} {val}")

# sample patched mah4cjt exprs
report = json.loads(
    (Path(__file__).resolve().parents[1] / ".dash-payloads" / "bgp-otel-patch-report.json").read_text()
)
mah = next(r for r in report if r.get("uid") == "mah4cjt")
print(f"\nmah4cjt changed: {mah.get('changed')}")
for s in mah.get("samples", [])[:3]:
    print("---")
    print("OLD:", s["old"][:120])
    print("NEW:", s["new"][:160])
