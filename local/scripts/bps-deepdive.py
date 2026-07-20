#!/usr/bin/env python3
"""Deep-dive kentik ifHC* series vs live device counters."""
from __future__ import annotations

import json
import re
import subprocess
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


def pq(env, expr):
    q = urllib.parse.urlencode({"query": expr})
    url = f"{env['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def cli(container, iface):
    out = subprocess.check_output(
        ["docker", "exec", container, "sr_cli", "-d", f"info from state interface {iface} statistics"],
        text=True,
    )
    inn = re.search(r"in-octets\s+(\d+)", out)
    outn = re.search(r"out-octets\s+(\d+)", out)
    return int(inn.group(1)) if inn else None, int(outn.group(1)) if outn else None


def snmpget(ip, oid):
    return int(
        subprocess.check_output(["snmpget", "-v2c", "-c", "public", "-Oqv", ip, oid], text=True)
        .strip()
        .strip('"')
    )


def main():
    env = load_env()
    report = {}

    # All series for leaf1
    for metric in ("kentik_snmp_ifHCInOctets", "kentik_snmp_ifHCOutOctets"):
        data = pq(env, f'{metric}{{device_name="leaf1"}}')
        rows = []
        for x in data["data"]["result"]:
            rows.append({"labels": x["metric"], "value": float(x["value"][1])})
        report[metric] = rows
        print(f"\n=== {metric} leaf1 ({len(rows)} series) ===")
        for r in sorted(rows, key=lambda z: z["labels"].get("if_interface_name", "")):
            labs = {k: v for k, v in r["labels"].items() if k != "__name__"}
            print(f"  {r['value']:>12.0f}  {labs}")

    # Live device
    ip = subprocess.check_output(
        ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", "leaf1"],
        text=True,
    ).split()[0]
    # ifindex map
    walk = subprocess.check_output(
        ["snmpwalk", "-v2c", "-c", "public", "-On", ip, "1.3.6.1.2.1.31.1.1.1.1"], text=True
    )
    imap = {}
    for line in walk.splitlines():
        m = re.search(r"1\.3\.6\.1\.2\.1\.31\.1\.1\.1\.1\.(\d+)\s*=\s*STRING:\s*\"?([^\"]+)\"?", line)
        if m:
            imap[m.group(2).strip()] = m.group(1)

    live = {}
    for iface in ("ethernet-1/1", "ethernet-1/49", "mgmt0", "mgmt0.0"):
        idx = imap.get(iface)
        entry = {"ifindex": idx}
        if idx:
            entry["snmp_in"] = snmpget(ip, f"1.3.6.1.2.1.31.1.1.1.6.{idx}")
            entry["snmp_out"] = snmpget(ip, f"1.3.6.1.2.1.31.1.1.1.10.{idx}")
        # CLI only for ethernet / mgmt0
        try:
            cin, cout = cli("leaf1", iface.replace(".0", "") if iface.endswith(".0") and iface != "mgmt0.0" else iface)
            # for mgmt0.0 try as-is
            if cin is None and iface == "mgmt0.0":
                cin, cout = cli("leaf1", "mgmt0")
            entry["cli_in"], entry["cli_out"] = cin, cout
        except Exception as e:
            entry["cli_err"] = str(e)
        live[iface] = entry
        print(f"LIVE {iface}: {entry}")
    report["live_leaf1"] = live

    # Double-count risk: sum vs max for parent+.0
    for kind, expr in (
        (
            "sum_in_leaf1",
            'sum by(if_interface_name) (rate(kentik_snmp_ifHCInOctets{device_name="leaf1"}[2m])*8)',
        ),
        (
            "max_in_leaf1",
            'max by(if_interface_name) (rate(kentik_snmp_ifHCInOctets{device_name="leaf1"}[2m])*8)',
        ),
        (
            "sum_without_subif",
            'sum by(if_interface_name) (rate(kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name!~".*\\\\.0$"}[2m])*8)',
        ),
    ):
        data = pq(env, expr)
        print(f"\n=== {kind} ===")
        for x in data["data"]["result"]:
            print(f"  {x['metric'].get('if_interface_name')}: {float(x['value'][1]):,.2f}")

    # GNMI live metric for leaf1
    data = pq(
        env,
        'gnmi_interface_stats_srl_nokia_interfaces:interface_statistics_in_octets{source="leaf1"}',
    )
    print("\n=== GNMI in_octets leaf1 ===")
    gnmi_rows = []
    for x in data["data"]["result"]:
        labs = {k: v for k, v in x["metric"].items() if k != "__name__"}
        gnmi_rows.append({"labels": labs, "value": float(x["value"][1])})
        # print only ethernet-ish
        name = json.dumps(labs)
        if "ethernet-1/1" in name or "ethernet-1/49" in name or "mgmt" in name:
            print(f"  {x['value'][1]} {labs}")
    report["gnmi_leaf1_in"] = gnmi_rows

    # Check if kentik values look like deltas / rates stored as gauges
    data = pq(env, 'kentik_snmp_PollingHealth{device_name="leaf1"}')
    print("\nPollingHealth", data["data"]["result"])

    # label keys on one series
    if report["kentik_snmp_ifHCInOctets"]:
        print("\nLabel keys:", sorted(report["kentik_snmp_ifHCInOctets"][0]["labels"].keys()))

    Path(ROOT / ".dash-payloads" / "iface-bps-deepdive.json").write_text(json.dumps(report, indent=2, default=str))
    print("wrote iface-bps-deepdive.json")


if __name__ == "__main__":
    main()
