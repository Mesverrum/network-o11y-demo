#!/usr/bin/env python3
"""Short-window traffic vs interface counter check + Prom query."""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sh(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout


def octets(container, iface):
    out = sh(["docker", "exec", container, "sr_cli", "-d", f"info from state interface {iface} statistics"])
    inn = re.search(r"in-octets\s+(\d+)", out)
    outn = re.search(r"out-octets\s+(\d+)", out)
    return int(inn.group(1)) if inn else 0, int(outn.group(1)) if outn else 0


def client_bytes(c):
    rx = int(sh(["docker", "exec", c, "cat", "/sys/class/net/eth1/statistics/rx_bytes"]))
    tx = int(sh(["docker", "exec", c, "cat", "/sys/class/net/eth1/statistics/tx_bytes"]))
    return rx, tx


def main():
    for c in ("client1", "client2"):
        print(c, sh(["docker", "exec", c, "sh", "-c", "pgrep -a iperf3 || true"], check=False).strip() or "none")
        print(sh(["docker", "exec", c, "sh", "-c", "ip addr show eth1; ip route"], check=False))

    for c in ("client1", "client2"):
        subprocess.run(["docker", "exec", c, "pkill", "-9", "iperf3"], capture_output=True)
    time.sleep(1)
    sh(["docker", "exec", "client1", "sh", "-c", "iperf3 -s -p 5201 -D"])
    sh(
        [
            "docker",
            "exec",
            "client2",
            "sh",
            "-c",
            "iperf3 -c 172.17.0.1 -u -b 20M -t 40 -i 2 --logfile /tmp/iperf3b.log >/dev/null 2>&1 &",
        ]
    )
    time.sleep(2)

    ifaces = {
        "leaf1": ["ethernet-1/1", "ethernet-1/49"],
        "leaf2": ["ethernet-1/1", "ethernet-1/49"],
        "spine1": ["ethernet-1/1", "ethernet-1/2"],
    }
    s1 = {d: {i: octets(d, i) for i in ifs} for d, ifs in ifaces.items()}
    c1a, c2a = client_bytes("client1"), client_bytes("client2")
    print("start", s1)
    time.sleep(20)
    s2 = {d: {i: octets(d, i) for i in ifs} for d, ifs in ifaces.items()}
    c1b, c2b = client_bytes("client1"), client_bytes("client2")
    dt = 20.0
    print("\n20s derived bps:")
    for d, ifs in ifaces.items():
        for i in ifs:
            din = (s2[d][i][0] - s1[d][i][0]) * 8 / dt
            dout = (s2[d][i][1] - s1[d][i][1]) * 8 / dt
            print(f"  {d} {i}: in={din:,.0f} out={dout:,.0f}")
    print(f"  client1 eth1: rx={(c1b[0]-c1a[0])*8/dt:,.0f} tx={(c1b[1]-c1a[1])*8/dt:,.0f}")
    print(f"  client2 eth1: rx={(c2b[0]-c2a[0])*8/dt:,.0f} tx={(c2b[1]-c2a[1])*8/dt:,.0f}")
    print("iperf log:\n", sh(["docker", "exec", "client2", "tail", "-20", "/tmp/iperf3b.log"], check=False))

    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    def pq(expr):
        q = urllib.parse.urlencode({"query": expr})
        url = f"{env['GRAFANA_URL'].rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    print("\nPROM top ifHCIn*8:")
    data = pq(
        'topk(15, sum by(device_name,if_interface_name)(rate(kentik_snmp_ifHCInOctets{device_name=~"leaf1|leaf2|spine1"}[2m])*8))'
    )
    for x in data["data"]["result"]:
        print(f"  {x['metric']} {float(x['value'][1]):,.1f}")

    print("\nPROM top ifHCOut*8:")
    data = pq(
        'topk(15, sum by(device_name,if_interface_name)(rate(kentik_snmp_ifHCOutOctets{device_name=~"leaf1|leaf2|spine1"}[2m])*8))'
    )
    for x in data["data"]["result"]:
        print(f"  {x['metric']} {float(x['value'][1]):,.1f}")

    print("\nGNMI octet metric names:")
    data = pq('count by (__name__) ({__name__=~"(?i).*octet.*"})')
    for x in data["data"]["result"]:
        print(" ", x["metric"].get("__name__"), x["value"][1])

    # Compare raw counter values in Prom vs live SNMP for leaf1 ethernet-1/49
    print("\nInstant kentik_snmp_ifHCInOctets leaf1:")
    data = pq('kentik_snmp_ifHCInOctets{device_name="leaf1",if_interface_name="ethernet-1/49"}')
    for x in data["data"]["result"]:
        print(" ", float(x["value"][1]))
    print("live SNMP/CLI leaf1 e1/49 in:", octets("leaf1", "ethernet-1/49")[0])

    out = {
        "s1": s1,
        "s2": s2,
        "client": {"c1": [c1a, c1b], "c2": [c2a, c2b]},
        "prom_in": data,
    }
    # rewrite with rates
    rates = {}
    for d, ifs in ifaces.items():
        rates[d] = {}
        for i in ifs:
            rates[d][i] = {
                "in_bps": (s2[d][i][0] - s1[d][i][0]) * 8 / dt,
                "out_bps": (s2[d][i][1] - s1[d][i][1]) * 8 / dt,
            }
    Path(ROOT / ".dash-payloads" / "iface-bps-shortwindow.json").write_text(
        json.dumps({"rates": rates, "client1_eth1_bps": {"rx": (c1b[0]-c1a[0])*8/dt, "tx": (c1b[1]-c1a[1])*8/dt},
                    "client2_eth1_bps": {"rx": (c2b[0]-c2a[0])*8/dt, "tx": (c2b[1]-c2a[1])*8/dt}}, indent=2)
    )


if __name__ == "__main__":
    main()
