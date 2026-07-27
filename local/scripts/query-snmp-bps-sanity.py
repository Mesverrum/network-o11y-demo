#!/usr/bin/env python3
"""Compare SNMP bps formulas vs lab expected traffic (~4 Mbps)."""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for line in (root / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

url = os.environ["GRAFANA_URL"]
token = os.environ["GRAFANA_TOKEN"]
base = f"{url}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query"


def query(q: str):
    req = urllib.request.Request(
        base + "?" + urllib.parse.urlencode({"query": q}),
        headers={"Authorization": f"Bearer {token}"},
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


def main() -> None:
    queries = {
        "top_iface_correct": (
            "topk(8, (kentik_snmp_ifHCInOctets{device_name=~\"spine1|leaf1|leaf2\"}) * 8 / 60)"
        ),
        "flow_rollup_bps": "sum(network_io_by_flow_bytes) * 8 / 60",
        "dash_per_device_in_plus_out": (
            '(sum by(device_name) (kentik_snmp_ifHCInOctets{device_name=~"spine1|leaf1|leaf2"}) '
            '+ sum by(device_name) (kentik_snmp_ifHCOutOctets{device_name=~"spine1|leaf1|leaf2"})) * 8 / 60'
        ),
        "dash_fleet_total": (
            "sum((kentik_snmp_ifHCInOctets{device_name=~\"spine1|leaf1|leaf2\"}) * 8 / 60) "
            "+ sum((kentik_snmp_ifHCOutOctets{device_name=~\"spine1|leaf1|leaf2\"}) * 8 / 60)"
        ),
        "dash_per_device_rate": (
            '(sum by(device_name) (rate(kentik_snmp_ifHCInOctets{device_name=~"spine1|leaf1|leaf2"}[5m])) '
            '+ sum by(device_name) (rate(kentik_snmp_ifHCOutOctets{device_name=~"spine1|leaf1|leaf2"}[5m]))) * 8'
        ),
    }
    for name, q in queries.items():
        print(f"=== {name} ===")
        data = query(q)
        for r in data.get("data", {}).get("result", [])[:10]:
            m = r.get("metric", {})
            val = float(r["value"][1])
            label = m.get("device_name", "fleet")
            print(f"  {label}: {val/1e6:.3f} Mbps")


if __name__ == "__main__":
    main()
