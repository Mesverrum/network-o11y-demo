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
    url = f"{env['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


d = pq('kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="ethernet-1/49"}')
print("n=", len(d["data"]["result"]))
for x in d["data"]["result"]:
    print("keys:", sorted(x["metric"].keys()))
    for k, v in sorted(x["metric"].items()):
        print(f"  {k}={v}")

print("\n=== any poll/time/dur labels on ifHC* leaf1 ===")
d = pq('{__name__=~"kentik_snmp_ifHC.*",device_name="leaf1"}')
labels = set()
pollish = []
for x in d["data"]["result"]:
    for k, v in x["metric"].items():
        labels.add(k)
        if any(s in k.lower() for s in ("poll", "time", "dur", "interval", "sec")):
            pollish.append(
                (
                    x["metric"].get("__name__"),
                    k,
                    v,
                    x["metric"].get("if_interface_name"),
                )
            )
print("all labels:", sorted(labels))
print("pollish:")
for p in pollish[:80]:
    print(" ", p)

print("\n=== IfInUtilization mgmt0 ===")
d = pq('kentik_snmp_IfInUtilization{device_name="leaf1",if_interface_name="mgmt0"}')
for x in d["data"]["result"]:
    for k, v in sorted(x["metric"].items()):
        print(f"  {k}={v}")

# Also dump raw via series API if available
print("\n=== label values containing poll across stack ===")
for label in (
    "PollDur",
    "poll_dur",
    "poll_time_sec",
    "poll_time",
    "PollingTime",
    "mib_poll_time_sec",
    "kt_poll_time_sec",
):
    try:
        d = pq(f'count({{__name__=~"kentik_snmp_.*",{label}=~".+"}})')
        print(label, d["data"]["result"])
    except Exception as e:
        print(label, e)
