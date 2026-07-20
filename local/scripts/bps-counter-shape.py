#!/usr/bin/env python3
"""Check whether kentik ifHC* is cumulative counter or per-interval delta."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def prom(env, path, params):
    q = urllib.parse.urlencode(params)
    url = f"{env['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/{path}?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    env = load_env()
    end = int(time.time())
    start = end - 30 * 60
    expr = 'kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="mgmt0"}'
    data = prom(env, "query_range", {"query": expr, "start": start, "end": end, "step": 60})
    series = data["data"]["result"]
    print(f"series count={len(series)}")
    for s in series:
        vals = [(int(t), float(v)) for t, v in s["values"]]
        print("points", len(vals))
        print("first10", vals[:10])
        print("last10", vals[-10:])
        # monotonic?
        deltas = [vals[i][1] - vals[i - 1][1] for i in range(1, len(vals))]
        neg = sum(1 for d in deltas if d < 0)
        zero = sum(1 for d in deltas if d == 0)
        pos = sum(1 for d in deltas if d > 0)
        print(f"delta signs: pos={pos} zero={zero} neg={neg}")
        if deltas:
            print(f"delta min/avg/max: {min(deltas):.1f}/{sum(deltas)/len(deltas):.1f}/{max(deltas):.1f}")
        # If values are deltas, bps ~= value*8/60
        last = vals[-1][1]
        print(f"if last value is per-poll delta: bps≈{last*8/60:,.1f}")
        print(f"if cumulative, rate() last window approx from last two: {(vals[-1][1]-vals[-2][1])*8/60:,.1f}")

    # Compare to live SNMP delta over one poll by waiting — skip; instead compare formula
    # Dashboard uses rate()*8. If metric is already delta/sec or delta/poll, show error factor.
    expr2 = 'rate(kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="mgmt0"}[2m]) * 8'
    inst = prom(env, "query", {"query": expr2})
    print("\ndashboard-style rate*8:", inst["data"]["result"])

    expr3 = 'kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="mgmt0"} * 8 / 60'
    inst = prom(env, "query", {"query": expr3})
    print("delta_gauge*8/poll:", inst["data"]["result"])

    # Also check ethernet-1/49
    expr = 'kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="ethernet-1/49"}'
    data = prom(env, "query_range", {"query": expr, "start": start, "end": end, "step": 60})
    vals = [(int(t), float(v)) for t, v in data["data"]["result"][0]["values"]]
    deltas = [vals[i][1] - vals[i - 1][1] for i in range(1, len(vals))]
    print("\nethernet-1/49 last10", vals[-10:])
    print(
        f"e1/49 delta signs pos={sum(d>0 for d in deltas)} neg={sum(d<0 for d in deltas)} "
        f"avg_delta={sum(deltas)/len(deltas):.1f}"
    )

    out = {
        "mgmt0_last10": vals[-10:] if False else None,
    }
    # save mgmt analysis
    Path(ROOT / ".dash-payloads" / "iface-bps-counter-shape.json").write_text(
        json.dumps(
            {
                "mgmt0_points_last20": [
                    {"t": t, "v": v}
                    for t, v in prom(env, "query_range", {"query": 'kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="mgmt0"}', "start": start, "end": end, "step": 60})[
                        "data"
                    ]["result"][0]["values"][-20:]
                ],
                "e149_points_last20": [
                    {"t": t, "v": v} for t, v in vals[-20:]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
