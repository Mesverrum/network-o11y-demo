#!/usr/bin/env python3
"""Restart traffic and finish BPS validation using Grafana datasource proxy."""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def sh(cmd: list[str], timeout: int = 120) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stderr}")
    return r.stdout


def restart_traffic() -> None:
    # Kill stale sessions
    for c in ("client1", "client2"):
        subprocess.run(["docker", "exec", c, "pkill", "-9", "iperf3"], capture_output=True)
    time.sleep(1)
    sh(["docker", "exec", "client1", "sh", "-c", "iperf3 -s -p 5201 -D --logfile /tmp/iperf3_5201.log"])
    # UDP is more reliable through this lab fabric for sustained rate
    sh(
        [
            "docker",
            "exec",
            "client2",
            "sh",
            "-c",
            "iperf3 -c 172.17.0.1 -p 5201 -u -b 10M -t 600 --logfile /tmp/iperf3.log -i 1 >/dev/null 2>&1 &",
        ]
    )
    time.sleep(3)
    log = sh(["docker", "exec", "client2", "tail", "-8", "/tmp/iperf3.log"])
    print("iperf tail:\n", log)


DEVICES = {
    "leaf1": ["ethernet-1/1", "ethernet-1/49"],
    "leaf2": ["ethernet-1/1", "ethernet-1/49"],
    "spine1": ["ethernet-1/1", "ethernet-1/2"],
}
OID_IFNAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"
OID_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"


def docker_ip(c: str) -> str:
    return sh(
        ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", c]
    ).split()[0]


def cli_octets(c: str, iface: str) -> tuple[int | None, int | None]:
    out = sh(["docker", "exec", c, "sr_cli", "-d", f"info from state interface {iface} statistics"])
    inn = re.search(r"in-octets\s+(\d+)", out)
    outn = re.search(r"out-octets\s+(\d+)", out)
    return (int(inn.group(1)) if inn else None, int(outn.group(1)) if outn else None)


def snmp_map(ip: str) -> dict[str, str]:
    out = sh(["snmpwalk", "-v2c", "-c", "public", "-On", ip, OID_IFNAME])
    m: dict[str, str] = {}
    for line in out.splitlines():
        mm = re.search(rf"\.{re.escape(OID_IFNAME)}\.(\d+)\s*=\s*STRING:\s*\"?([^\"]+)\"?", line)
        if mm:
            m[mm.group(2).strip()] = mm.group(1)
    return m


def snmp_octets(ip: str, idx: str) -> tuple[int, int]:
    inn = int(sh(["snmpget", "-v2c", "-c", "public", "-Oqv", ip, f"{OID_HC_IN}.{idx}"]).strip().strip('"'))
    out = int(sh(["snmpget", "-v2c", "-c", "public", "-Oqv", ip, f"{OID_HC_OUT}.{idx}"]).strip().strip('"'))
    return inn, out


def gnmi_octets(target: str, iface: str) -> tuple[int | None, int | None]:
    out = sh(
        [
            "docker",
            "exec",
            "gnmic",
            "/app/gnmic",
            "-a",
            f"{target}:57400",
            "-u",
            "admin",
            "-p",
            "NokiaSrl1!",
            "--skip-verify",
            "get",
            "--path",
            f"/interface[name={iface}]/statistics",
            "-e",
            "json_ietf",
        ]
    )
    inn = re.search(r'"in-octets"\s*:\s*"?(\d+)"?', out)
    outn = re.search(r'"out-octets"\s*:\s*"?(\d+)"?', out)
    return (int(inn.group(1)) if inn else None, int(outn.group(1)) if outn else None)


def prom_query(gurl: str, gtok: str, expr: str) -> dict:
    q = urllib.parse.urlencode({"query": expr})
    url = f"{gurl.rstrip('/')}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {gtok}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def bps(a, b, dt):
    if a is None or b is None or dt <= 0:
        return None
    return (b - a) * 8.0 / dt


def pct(a, b):
    if a is None or b is None:
        return None
    if a == 0 and b == 0:
        return 0.0
    return 100.0 * (b - a) / max(abs(a), abs(b), 1.0)


def sample_all(meta):
    snap = {"t": time.time(), "iso": datetime.now(timezone.utc).isoformat(), "devices": {}}
    for name, m in meta.items():
        snap["devices"][name] = {}
        for iface in m["ifaces"]:
            e = {}
            e["cli_in"], e["cli_out"] = cli_octets(m["container"], iface)
            idx = m["ifindex"].get(iface)
            if idx:
                e["snmp_in"], e["snmp_out"] = snmp_octets(m["ip"], idx)
                e["ifindex"] = idx
            e["gnmi_in"], e["gnmi_out"] = gnmi_octets(name, iface)
            snap["devices"][name][iface] = e
            print(
                f"  {name} {iface}: cli=({e['cli_in']},{e['cli_out']}) "
                f"snmp=({e.get('snmp_in')},{e.get('snmp_out')}) "
                f"gnmi=({e.get('gnmi_in')},{e.get('gnmi_out')})"
            )
    return snap


def main() -> None:
    env = load_env()
    gurl, gtok = env["GRAFANA_URL"], env["GRAFANA_TOKEN"]
    print("Restarting UDP iperf 10M...")
    restart_traffic()

    meta = {}
    for name, ifaces in DEVICES.items():
        ip = docker_ip(name)
        imap = snmp_map(ip)
        meta[name] = {"container": name, "ip": ip, "ifaces": ifaces, "ifindex": imap}
        print(name, ip, {i: imap.get(i) for i in ifaces})

    gap = 90
    samples = []
    for n in range(2):
        print(f"\n=== sample {n+1}/2 ===")
        samples.append(sample_all(meta))
        if n == 0:
            print(f"sleep {gap}s...")
            time.sleep(gap)

    a, b = samples
    dt = b["t"] - a["t"]
    joined = []
    for name in DEVICES:
        for iface in DEVICES[name]:
            ea, eb = a["devices"][name][iface], b["devices"][name][iface]
            for direction, cli_a, cli_b, snmp_a, snmp_b, gnmi_a, gnmi_b in (
                (
                    "in",
                    ea.get("cli_in"),
                    eb.get("cli_in"),
                    ea.get("snmp_in"),
                    eb.get("snmp_in"),
                    ea.get("gnmi_in"),
                    eb.get("gnmi_in"),
                ),
                (
                    "out",
                    ea.get("cli_out"),
                    eb.get("cli_out"),
                    ea.get("snmp_out"),
                    eb.get("snmp_out"),
                    ea.get("gnmi_out"),
                    eb.get("gnmi_out"),
                ),
            ):
                row = {
                    "device": name,
                    "iface": iface,
                    "direction": direction,
                    "dt_sec": round(dt, 1),
                    "cli_bps": bps(cli_a, cli_b, dt),
                    "snmp_bps": bps(snmp_a, snmp_b, dt),
                    "gnmi_bps": bps(gnmi_a, gnmi_b, dt),
                }
                joined.append(row)

    # PromQL dashboard-style queries at several windows
    prom = []
    for win in (60, 90, 120, 300):
        for direction, metric in (("in", "kentik_snmp_ifHCInOctets"), ("out", "kentik_snmp_ifHCOutOctets")):
            expr = (
                f'sum by (device_name, if_interface_name) '
                f'(rate({metric}{{device_name=~"leaf1|leaf2|spine1"}}[{win}s])) * 8'
            )
            data = prom_query(gurl, gtok, expr)
            for r in data.get("data", {}).get("result", []):
                prom.append(
                    {
                        "window": f"{win}s",
                        "direction": direction,
                        "device": r["metric"].get("device_name"),
                        "iface": r["metric"].get("if_interface_name"),
                        "prom_bps": float(r["value"][1]),
                    }
                )

    # gnmi metric discovery
    gnmi_names = prom_query(
        gurl,
        gtok,
        'count by (__name__) ({__name__=~"(?i).*octet.*", service_name="gnmic"})',
    )

    # Also try common gnmi metric patterns for rates
    gnmi_prom = []
    for cand in (
        'sum by (source, interface_name) (rate(gnmi_interface_statistics_in_octets{source=~"leaf1|leaf2|spine1"}[120s])) * 8',
        'sum by (source, name) (rate(gnmi_interface_stats_interface_statistics_in_octets{source=~"leaf1|leaf2|spine1"}[120s])) * 8',
        'sum by (target, interface_name) (rate({__name__=~"gnmi_.*in_octets.*", service_name="gnmic"}[120s])) * 8',
    ):
        try:
            data = prom_query(gurl, gtok, cand)
            gnmi_prom.append({"expr": cand, "result": data.get("data", {}).get("result", [])[:20]})
        except Exception as e:
            gnmi_prom.append({"expr": cand, "error": str(e)})

    # Join with prom 120s
    for row in joined:
        matches = [
            p
            for p in prom
            if p["device"] == row["device"]
            and p["iface"] == row["iface"]
            and p["direction"] == row["direction"]
            and p["window"] == "120s"
        ]
        row["prom_120s_bps"] = matches[0]["prom_bps"] if matches else None
        row["snmp_vs_cli_pct"] = pct(row["cli_bps"], row["snmp_bps"])
        row["gnmi_vs_cli_pct"] = pct(row["cli_bps"], row["gnmi_bps"])
        row["prom_vs_cli_pct"] = pct(row["cli_bps"], row["prom_120s_bps"])
        row["prom_vs_snmp_pct"] = pct(row["snmp_bps"], row["prom_120s_bps"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "traffic": "iperf3 UDP client2→client1 10M",
        "poll": {"snmp_sec": 60, "gnmi_sec": 30, "sample_gap_sec": gap},
        "dashboard_query": "rate(kentik_snmp_ifHCIn/OutOctets[$__rate_interval]) * 8",
        "samples": samples,
        "joined": joined,
        "prom": prom,
        "gnmi_metric_names": gnmi_names,
        "gnmi_prom_trials": gnmi_prom,
    }
    out = ROOT / ".dash-payloads" / "iface-bps-validation.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {out}")

    print(
        f"\n{'device':8} {'iface':14} {'dir':3} {'cli':>10} {'snmp':>10} {'gnmi':>10} {'prom120':>10} "
        f"{'snmp%':>8} {'gnmi%':>8} {'prom%':>8}"
    )
    for j in joined:
        def f(v):
            return f"{v:,.0f}" if isinstance(v, (int, float)) else "-"

        def p(v):
            return f"{v:+.1f}%" if isinstance(v, (int, float)) else "-"

        # only show interfaces with meaningful traffic
        vals = [j["cli_bps"], j["snmp_bps"], j["gnmi_bps"], j["prom_120s_bps"]]
        if not any(isinstance(v, (int, float)) and abs(v) > 1000 for v in vals):
            continue
        print(
            f"{j['device']:8} {j['iface']:14} {j['direction']:3} "
            f"{f(j['cli_bps']):>10} {f(j['snmp_bps']):>10} {f(j['gnmi_bps']):>10} {f(j['prom_120s_bps']):>10} "
            f"{p(j['snmp_vs_cli_pct']):>8} {p(j['gnmi_vs_cli_pct']):>8} {p(j['prom_vs_cli_pct']):>8}"
        )


if __name__ == "__main__":
    main()
