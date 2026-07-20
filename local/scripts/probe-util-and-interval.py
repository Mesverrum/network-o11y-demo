#!/usr/bin/env python3
"""Check IfInUtilization and whether timestamp gaps encode poll interval."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

env = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()


def pq(expr, path="query", **extra):
    params = {"query": expr, **extra}
    q = urllib.parse.urlencode(params)
    url = f"{env['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/{path}?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


print("=== IfIn/OutUtilization leaf1 ===")
for m in ("kentik_snmp_IfInUtilization", "kentik_snmp_IfOutUtilization"):
    d = pq(f'{m}{{device_name="leaf1"}}')
    for x in d["data"]["result"]:
        labs = {k: x["metric"][k] for k in ("if_interface_name", "if_Speed") if k in x["metric"]}
        print(m, float(x["value"][1]), labs)

print("\n=== derive bps from util * speed ===")
# util is percent; speed in Mbps → bps = util/100 * speed * 1e6
d = pq(
    'kentik_snmp_IfInUtilization{device_name="leaf1"} '
    '* on(device_name, if_interface_name) group_left(if_Speed) '
    'kentik_snmp_ifHCInOctets{device_name="leaf1"} * 0 + 1'  # noop join attempt
)
# simpler: just get both
util = {
    x["metric"]["if_interface_name"]: float(x["value"][1])
    for x in pq('kentik_snmp_IfInUtilization{device_name="leaf1"}')["data"]["result"]
}
oct_series = pq('kentik_snmp_ifHCInOctets{device_name="leaf1"}')["data"]["result"]
for x in oct_series:
    name = x["metric"]["if_interface_name"]
    speed = float(x["metric"].get("if_Speed") or 0)
    delta = float(x["value"][1])
    u = util.get(name)
    bps_from_delta = delta * 8 / 60
    bps_from_util = (u / 100.0 * speed * 1_000_000) if u is not None and speed else None
    print(
        f"{name}: delta={delta:.0f} speed={speed} util={u} "
        f"bps_delta60={bps_from_delta:.1f} bps_util={bps_from_util}"
    )

print("\n=== sample interval from query_range timestamps (mgmt0) ===")
end = int(time.time())
start = end - 15 * 60
d = pq(
    'kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="mgmt0"}',
    path="query_range",
    start=start,
    end=end,
    step=15,
)
vals = d["data"]["result"][0]["values"]
# unique timestamps where value changed
changes = [(int(vals[0][0]), float(vals[0][1]))]
for t, v in vals[1:]:
    if float(v) != changes[-1][1]:
        changes.append((int(t), float(v)))
gaps = [changes[i][0] - changes[i - 1][0] for i in range(1, len(changes))]
print("change count", len(changes), "gaps", gaps[:20])
if gaps:
    print(f"gap min/avg/max {min(gaps)}/{sum(gaps)/len(gaps):.1f}/{max(gaps)}")
