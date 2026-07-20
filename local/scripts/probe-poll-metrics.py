#!/usr/bin/env python3
import json
import urllib.parse
import urllib.request
from pathlib import Path

env = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()


def pq(expr):
    q = urllib.parse.urlencode({"query": expr})
    url = (
        f"{env['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


print("=== poll-ish metric names ===")
d = pq('count by (__name__) ({__name__=~"(?i)kentik_snmp_.*([Pp]oll|[Tt]ime|[Ii]nterval).*"})')
for x in d["data"]["result"]:
    print(x["metric"].get("__name__"), x["value"][1])

print("\n=== all kentik_snmp metric names (leaf) ===")
d = pq('count by (__name__) ({__name__=~"kentik_snmp_.*", device_name="leaf1"})')
for x in sorted(d["data"]["result"], key=lambda z: z["metric"].get("__name__", "")):
    print(x["metric"].get("__name__"), x["value"][1])

for m in (
    "kentik_snmp_DeviceMetrics",
    "kentik_snmp_PollingHealth",
    "kentik_snmp_MinPollingTime",
    "kentik_snmp_MaxPollingTime",
    "kentik_snmp_AvgPollingTime",
    "kentik_snmp_PollingTime",
    "kentik_snmp_poll_duration",
):
    d = pq(f'{m}{{device_name="leaf1"}}')
    print(f"\n=== {m} n={len(d['data']['result'])} ===")
    for x in d["data"]["result"][:5]:
        labs = {k: v for k, v in x["metric"].items() if k != "__name__"}
        print(" ", x["value"][1], labs)
