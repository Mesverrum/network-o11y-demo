#!/usr/bin/env python3
"""Confirm gnmic OTEL value-as-label behavior against Grafana Cloud Prom."""
import json
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

env = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

base = env["GRAFANA_URL"].rstrip("/")
hdr = {"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"}


def pq(q: str):
    url = (
        base
        + "/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?"
        + urllib.parse.urlencode({"query": q})
    )
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


# series count over last 6h for cardinality
def series_count(match: str) -> int:
    url = (
        base
        + "/api/datasources/proxy/uid/grafanacloud-prom/api/v1/series?"
        + urllib.parse.urlencode(
            {
                "match[]": match,
                "start": str(int(__import__("time").time()) - 6 * 3600),
                "end": str(int(__import__("time").time())),
            }
        )
    )
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=120) as r:
        return len(json.load(r).get("data", []))


checks = [
    ("in_octets", '{__name__=~"gnmi_interface_stats.*in_octets",source="leaf1"}'),
    ("out_octets", '{__name__=~"gnmi_interface_stats.*out_octets",source="leaf1"}'),
    ("mem_free", '{__name__=~"gnmi_system_resources.*memory_free",source="leaf1"}'),
    ("mem_util", '{__name__=~"gnmi_system_resources.*memory_utilization",source="leaf1"}'),
    ("cpu1", '{__name__=~"gnmi_system_resources.*cpu_total_average_1",source="leaf1"}'),
    ("bgp_peer_as", '{__name__=~"gnmi_bgp.*peer_as",source="leaf1"}'),
    ("bgp_session", '{__name__=~"gnmi_bgp.*session_state",source="leaf1"}'),
]

for name, q in checks:
    res = pq(q)["data"]["result"]
    print(f"\n=== {name} instant_series={len(res)} ===")
    if not res:
        continue
    for s in res[:2]:
        m = s["metric"]
        print(
            f"  prom={s['value'][1]} value_lbl={m.get('value')!r} "
            f"iface={m.get('interface_name')} "
            f"name=...{m.get('__name__','')[-50:]}"
        )
    nums = [float(s["value"][1]) for s in res]
    vals = [s["metric"].get("value") for s in res if "value" in s["metric"]]
    print(f"  prom_value_hist={Counter(nums).most_common(3)}")
    print(f"  has_value_label={len(vals)}/{len(res)} unique_value_lbls={len(set(vals))}")
    try:
        sc = series_count(q)
        print(f"  series_last_6h={sc}")
    except Exception as e:
        print(f"  series_last_6h_err={e}")
