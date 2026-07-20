#!/usr/bin/env python3
"""Confirm whether poll_duration_sec (or similar) appears on lab kentik metrics."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()


def pq(expr: str) -> dict:
    q = urllib.parse.urlencode({"query": expr})
    url = (
        f"{env['GRAFANA_URL'].rstrip('/')}"
        f"/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    )
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


POLL_LABEL_CANDIDATES = (
    "poll_duration_sec",
    "poll_time_sec",
    "poll_time",
    "PollDur",
    "poll_dur",
    "PollingTime",
    "kt_poll_time_sec",
    "mib_poll_time_sec",
)

print("=== A) series with any poll_* label (stack-wide) ===")
for lab in POLL_LABEL_CANDIDATES:
    d = pq(f'count({{{lab}=~".+"}})')
    n = d["data"]["result"][0]["value"][1] if d["data"]["result"] else "0"
    print(f"  {lab}: {n}")

print("\n=== B) kentik_snmp_* with poll_duration_sec ===")
d = pq('count({__name__=~"kentik_snmp_.*", poll_duration_sec=~".+"})')
print(" ", d["data"]["result"])

print("\n=== C) full label inventory on leaf1 ifHCInOctets (all ifaces) ===")
d = pq('kentik_snmp_ifHCInOctets{device_name="leaf1"}')
label_counts: Counter[str] = Counter()
sample = None
for x in d["data"]["result"]:
    sample = x["metric"]
    label_counts.update(x["metric"].keys())
print(f"  series count: {len(d['data']['result'])}")
print(f"  union of label keys ({len(label_counts)}):")
for k in sorted(label_counts):
    print(f"    {k} (on {label_counts[k]}/{len(d['data']['result'])} series)")
if sample:
    print("\n  example series labels:")
    for k, v in sorted(sample.items()):
        print(f"    {k}={v}")

print("\n=== D) label_values-style: count by label name presence ===")
# Any metric on lab devices with poll_duration_sec
d = pq(
    'count by (__name__) ({device_name=~"leaf1|leaf2|spine1", poll_duration_sec=~".+"})'
)
print("  metrics with poll_duration_sec on lab devices:", d["data"]["result"] or "(none)")

print("\n=== E) dashboard-style query used in Netterfield WIP ===")
d = pq('count by(poll_duration_sec) ({device_name=~"leaf1|leaf2|spine1", poll_duration_sec!=""})')
print(" ", d["data"]["result"] or "(empty — label absent)")

out = {
    "poll_label_counts": {},
    "leaf1_ifHCIn_label_keys": sorted(label_counts),
    "example": sample,
}
for lab in POLL_LABEL_CANDIDATES:
    d = pq(f'count({{{lab}=~".+"}})')
    out["poll_label_counts"][lab] = (
        d["data"]["result"][0]["value"][1] if d["data"]["result"] else "0"
    )

(ROOT / ".dash-payloads" / "poll-label-confirmation.json").write_text(
    json.dumps(out, indent=2)
)
print("\nWrote local/.dash-payloads/poll-label-confirmation.json")
