#!/usr/bin/env python3
"""Compare live SNMP 60s delta*8/dt vs Prom rate()*8 vs delta*8/60."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OID_IN = "1.3.6.1.2.1.31.1.1.1.6"
OID_OUT = "1.3.6.1.2.1.31.1.1.1.10"


def env():
    e = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip()
    return e


def pq(e, expr):
    q = urllib.parse.urlencode({"query": expr})
    url = f"{e['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {e['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def snmp(ip, oid):
    return int(
        subprocess.check_output(["snmpget", "-v2c", "-c", "public", "-Oqv", ip, oid], text=True)
        .strip()
        .strip('"')
    )


def main():
    e = env()
    ip = subprocess.check_output(
        ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", "leaf1"],
        text=True,
    ).split()[0]
    # ifindexes from prior run
    targets = {
        "ethernet-1/1": "16382",
        "ethernet-1/49": "1589246",
        "mgmt0": "1077952510",
    }
    t0 = time.time()
    a = {n: (snmp(ip, f"{OID_IN}.{i}"), snmp(ip, f"{OID_OUT}.{i}")) for n, i in targets.items()}
    print("sample A", a)
    time.sleep(60)
    t1 = time.time()
    b = {n: (snmp(ip, f"{OID_IN}.{i}"), snmp(ip, f"{OID_OUT}.{i}")) for n, i in targets.items()}
    dt = t1 - t0
    print("sample B", b, "dt", dt)

    rows = []
    for name in targets:
        live_in = (b[name][0] - a[name][0]) * 8 / dt
        live_out = (b[name][1] - a[name][1]) * 8 / dt
        # Prom formulas
        rate_in = pq(
            e,
            f'rate(kentik_snmp_ifHCInOctets{{device_name="leaf1",if_interface_name="{name}"}}[2m]) * 8',
        )
        rate_out = pq(
            e,
            f'rate(kentik_snmp_ifHCOutOctets{{device_name="leaf1",if_interface_name="{name}"}}[2m]) * 8',
        )
        delta_in = pq(
            e,
            f'kentik_snmp_ifHCInOctets{{device_name="leaf1",if_interface_name="{name}"}} * 8 / 60',
        )
        delta_out = pq(
            e,
            f'kentik_snmp_ifHCOutOctets{{device_name="leaf1",if_interface_name="{name}"}} * 8 / 60',
        )

        def val(data):
            r = data.get("data", {}).get("result", [])
            return float(r[0]["value"][1]) if r else None

        row = {
            "iface": name,
            "live_snmp_in_bps": live_in,
            "live_snmp_out_bps": live_out,
            "dashboard_rate_in_bps": val(rate_in),
            "dashboard_rate_out_bps": val(rate_out),
            "corrected_delta_in_bps": val(delta_in),
            "corrected_delta_out_bps": val(delta_out),
            "kentik_raw_in": val(pq(e, f'kentik_snmp_ifHCInOctets{{device_name="leaf1",if_interface_name="{name}"}}')),
            "kentik_raw_out": val(pq(e, f'kentik_snmp_ifHCOutOctets{{device_name="leaf1",if_interface_name="{name}"}}')),
            "snmp_abs_in": b[name][0],
            "snmp_abs_out": b[name][1],
        }
        for d in ("in", "out"):
            live = row[f"live_snmp_{d}_bps"]
            dash = row[f"dashboard_rate_{d}_bps"]
            corr = row[f"corrected_delta_{d}_bps"]
            row[f"dash_err_pct_{d}"] = None if live is None or dash is None or live == 0 else 100 * (dash - live) / live
            row[f"corr_err_pct_{d}"] = None if live is None or corr is None or live == 0 else 100 * (corr - live) / live
        rows.append(row)
        print(json.dumps(row, indent=2))

    Path(ROOT / ".dash-payloads" / "iface-bps-verdict.json").write_text(json.dumps({"dt": dt, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
