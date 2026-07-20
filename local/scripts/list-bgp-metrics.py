#!/usr/bin/env python3
"""List live gnmi BGP metric names and sample labels from Grafana Cloud Prom."""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

env = Path(__file__).resolve().parents[1] / ".env"
for line in env.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

base = os.environ["GRAFANA_URL"].rstrip("/")
tok = os.environ["GRAFANA_TOKEN"]
hdr = {"Authorization": f"Bearer {tok}"}


def get(path, params=None):
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def pq(q):
    return get(
        "/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query",
        {"query": q},
    )


names = get(
    "/api/datasources/proxy/uid/grafanacloud-prom/api/v1/label/__name__/values",
    {"match[]": '{__name__=~"gnmi_bgp.*"}'},
)["data"]
print(f"gnmi_bgp metric names: {len(names)}")
for n in sorted(names):
    print(f"  {n}")

# search dashboards with bgp in title
search = get("/api/search", {"query": "bgp", "type": "dash-db"})
print("\nBGP dashboards:")
for d in search:
    print(f"  {d.get('uid')}  {d.get('title')}  ({d.get('folderTitle')})")

# sample one series for key suffixes
suffixes = [
    "session_state",
    "established_transitions",
    "peer_as",
    "afi_safi_received_routes",
    "afi_safi_active_routes",
    "afi_safi_sent_routes",
    "admin_state",
    "received_messages_total_updates",
    "sent_messages_total_updates",
    "received_updates",
    "sent_updates",
]
prefix = "gnmi_bgp_neighbors_srl_nokia_network_instance:network_instance_protocols_srl_nokia_bgp:bgp_neighbor_"
print("\nSuffix presence:")
for s in suffixes:
    name = prefix + s
    res = pq(f'count({{__name__="{name}"}})')["data"]["result"]
    val = res[0]["value"][1] if res else "0"
    print(f"  {s}: {val}")

# labels on session_state
ss = pq(
    f'{{__name__="{prefix}session_state"}}'
)["data"]["result"]
if ss:
    print("\nsession_state sample labels:", json.dumps(ss[0]["metric"], indent=2))
    print("value:", ss[0]["value"][1])
