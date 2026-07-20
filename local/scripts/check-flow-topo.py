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
    url = f"{env['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

queries = {
    "flow series now": 'count({__name__=~"network_io_by_flow.*"})',
    "flow rate 5m": 'sum(rate(network_io_by_flow[5m])) or sum(rate(network_io_by_flow_bytes[5m])) or vector(0)',
    "topo devices": 'count(network_topology_device_info{tester_id="network-lab"})',
    "topo edges": 'count(network_topology_edge_info{tester_id="network-lab"})',
    "snmp devices": 'count by (device_name) (kentik_snmp_Uptime)',
}
for name, expr in queries.items():
    try:
        d = pq(expr)
        print(name, "->", d.get("data", {}).get("result"))
    except Exception as e:
        print(name, "ERR", e)
