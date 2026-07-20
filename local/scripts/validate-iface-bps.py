#!/usr/bin/env python3
"""Cross-check interface bps: CLI vs SNMP vs gNMI vs Grafana PromQL.

Samples counters twice (and optionally thrice) across poll-aware windows,
derives independent rates, and compares to dashboard-style PromQL:

  rate(kentik_snmp_ifHCInOctets[...]) * 8

Run inside WSL from local/:  python3 scripts/validate-iface-bps.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

# Clos fabric: client1 sits behind leaf1; client2 behind leaf2; spine1 in the middle.
# Traffic path client2→client1 hits leaf2 uplink + leaf1 uplink + leaf1 client port.
# Clos links (topology.clab.yml): leaf e1-1↔client, leaf e1-49↔spine, spine e1-1/2↔leaves
DEVICES = {
    "leaf1": {"container": "leaf1", "ifaces": ["ethernet-1/1", "ethernet-1/49"]},
    "leaf2": {"container": "leaf2", "ifaces": ["ethernet-1/1", "ethernet-1/49"]},
    "spine1": {"container": "spine1", "ifaces": ["ethernet-1/1", "ethernet-1/2"]},
}

# SNMP IF-MIB
OID_IFNAME = "1.3.6.1.2.1.31.1.1.1.1"  # ifName
OID_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"  # ifHCInOctets
OID_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"  # ifHCOutOctets

SNMP_COMMUNITY = os.environ.get("SNMP_COMMUNITY", "public")
SAMPLE_GAP_SEC = int(os.environ.get("BPS_SAMPLE_GAP", "90"))  # > SNMP 60s poll
NUM_SAMPLES = int(os.environ.get("BPS_NUM_SAMPLES", "3"))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def sh(cmd: list[str], timeout: int = 60) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr}")
    return r.stdout


def docker_ip(container: str) -> str:
    out = sh(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
            container,
        ]
    )
    ips = [p for p in out.split() if p]
    if not ips:
        raise RuntimeError(f"no IP for {container}")
    return ips[0]


def cli_octets(container: str, iface: str) -> tuple[int | None, int | None]:
    out = sh(
        [
            "docker",
            "exec",
            container,
            "sr_cli",
            "-d",
            f"info from state interface {iface} statistics",
        ]
    )
    inn = re.search(r"in-octets\s+(\d+)", out)
    outn = re.search(r"out-octets\s+(\d+)", out)
    return (
        int(inn.group(1)) if inn else None,
        int(outn.group(1)) if outn else None,
    )


def snmp_walk(ip: str, oid: str) -> dict[str, str]:
    """Return {index: value} from snmpwalk."""
    out = sh(
        [
            "snmpwalk",
            "-v2c",
            "-c",
            SNMP_COMMUNITY,
            "-On",
            ip,
            oid,
        ],
        timeout=90,
    )
    result: dict[str, str] = {}
    for line in out.splitlines():
        # .1.3.6.1.2.1.31.1.1.1.1.12 = STRING: "ethernet-1/1"
        m = re.match(
            rf"\.{re.escape(oid)}\.(\d+)\s*=\s*(?:STRING:|Counter64:|Gauge32:|INTEGER:)\s*\"?([^\"]+)\"?",
            line,
        )
        if not m:
            # alternate formats
            m = re.match(rf".*\.(\d+)\s*=\s*(?:STRING:|Counter64:)\s*\"?([^\"]+)\"?", line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


def snmp_iface_map(ip: str) -> dict[str, str]:
    """ifName -> ifIndex"""
    names = snmp_walk(ip, OID_IFNAME)
    return {v: k for k, v in names.items()}


def snmp_get_int(ip: str, oid: str) -> int:
    out = sh(["snmpget", "-v2c", "-c", SNMP_COMMUNITY, "-Oqv", ip, oid], timeout=30)
    return int(out.strip().strip('"'))


def snmp_octets(ip: str, ifindex: str) -> tuple[int, int]:
    return snmp_get_int(ip, f"{OID_HC_IN}.{ifindex}"), snmp_get_int(ip, f"{OID_HC_OUT}.{ifindex}")


def gnmi_get_octets(target: str, iface: str) -> tuple[int | None, int | None]:
    """Use gnmic get against target:57400 for interface statistics."""
    # Prefer docker exec into gnmic container if present
    path = f"/interface[name={iface}]/statistics"
    try:
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
                path,
                "-e",
                "json_ietf",
            ],
            timeout=30,
        )
    except Exception as e:
        return None, None
    # parse in-octets / out-octets from JSON-ish or text
    inn = re.search(r'"in-octets"\s*:\s*"?(\d+)"?', out) or re.search(
        r"in-octets[\"']?\s*[:=]\s*\"?(\d+)", out
    )
    outn = re.search(r'"out-octets"\s*:\s*"?(\d+)"?', out) or re.search(
        r"out-octets[\"']?\s*[:=]\s*\"?(\d+)", out
    )
    return (
        int(inn.group(1)) if inn else None,
        int(outn.group(1)) if outn else None,
    )


def prom_query(base_url: str, user: str, token: str, query: str) -> dict:
    url = base_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    auth = b64encode(f"{user}:{token}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def bps_from_delta(a: int | None, b: int | None, dt: float) -> float | None:
    if a is None or b is None or dt <= 0:
        return None
    return (b - a) * 8.0 / dt


def pct_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    if a == 0 and b == 0:
        return 0.0
    denom = max(abs(a), abs(b), 1.0)
    return 100.0 * (b - a) / denom


def main() -> int:
    env = load_env()
    prom_url = env.get("GC_PROM_URL", "")
    prom_user = env.get("GC_PROM_USER", "")
    # Prefer dedicated metrics token; OTLP key often works for same stack
    prom_token = env.get("GC_PROM_TOKEN") or env.get("GC_OTLP_KEY", "")
    if not (prom_url and prom_user and prom_token):
        print("missing GC_PROM_URL / GC_PROM_USER / GC_OTLP_KEY in local/.env", file=sys.stderr)
        return 1

    # Ensure snmp tools
    try:
        sh(["snmpwalk", "-V"])
    except Exception:
        print("installing snmp...", file=sys.stderr)
        subprocess.run(["sudo", "apt-get", "update", "-qq"], check=False)
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "-qq", "snmp", "snmp-mibs-downloader"],
            check=False,
        )

    # Resolve device IPs and ifIndex maps once
    meta: dict[str, dict] = {}
    for name, cfg in DEVICES.items():
        ip = docker_ip(cfg["container"])
        try:
            imap = snmp_iface_map(ip)
        except Exception as e:
            print(f"WARN snmp map {name}: {e}", file=sys.stderr)
            imap = {}
        meta[name] = {"ip": ip, "container": cfg["container"], "ifaces": cfg["ifaces"], "ifindex": imap}
        print(f"{name} ip={ip} ifaces={cfg['ifaces']}")
        for iface in cfg["ifaces"]:
            print(f"  {iface} -> ifIndex={imap.get(iface, '?')}")

    samples: list[dict] = []
    for n in range(NUM_SAMPLES):
        ts = time.time()
        snap: dict = {"t": ts, "iso": datetime.now(timezone.utc).isoformat(), "devices": {}}
        for name, m in meta.items():
            snap["devices"][name] = {}
            for iface in m["ifaces"]:
                entry: dict = {}
                try:
                    cin, cout = cli_octets(m["container"], iface)
                    entry["cli_in"], entry["cli_out"] = cin, cout
                except Exception as e:
                    entry["cli_err"] = str(e)
                idx = m["ifindex"].get(iface)
                if idx:
                    try:
                        sin, sout = snmp_octets(m["ip"], idx)
                        entry["snmp_in"], entry["snmp_out"] = sin, sout
                        entry["ifindex"] = idx
                    except Exception as e:
                        entry["snmp_err"] = str(e)
                try:
                    gin, gout = gnmi_get_octets(name, iface)
                    entry["gnmi_in"], entry["gnmi_out"] = gin, gout
                except Exception as e:
                    entry["gnmi_err"] = str(e)
                snap["devices"][name][iface] = entry
        samples.append(snap)
        print(f"\n=== sample {n+1}/{NUM_SAMPLES} @ {snap['iso']} ===")
        for name, ifaces in snap["devices"].items():
            for iface, e in ifaces.items():
                print(
                    f"  {name} {iface}: "
                    f"cli=({e.get('cli_in')},{e.get('cli_out')}) "
                    f"snmp=({e.get('snmp_in')},{e.get('snmp_out')}) "
                    f"gnmi=({e.get('gnmi_in')},{e.get('gnmi_out')})"
                )
        if n < NUM_SAMPLES - 1:
            print(f"sleeping {SAMPLE_GAP_SEC}s (SNMP poll=60s, gNMI=30s)...")
            time.sleep(SAMPLE_GAP_SEC)

    # Derive rates between consecutive samples
    comparisons: list[dict] = []
    for i in range(1, len(samples)):
        a, b = samples[i - 1], samples[i]
        dt = b["t"] - a["t"]
        for name in meta:
            for iface in meta[name]["ifaces"]:
                ea = a["devices"][name].get(iface, {})
                eb = b["devices"][name].get(iface, {})
                row = {
                    "window": f"s{i}-s{i+1}",
                    "dt_sec": round(dt, 1),
                    "device": name,
                    "iface": iface,
                    "cli_in_bps": bps_from_delta(ea.get("cli_in"), eb.get("cli_in"), dt),
                    "cli_out_bps": bps_from_delta(ea.get("cli_out"), eb.get("cli_out"), dt),
                    "snmp_in_bps": bps_from_delta(ea.get("snmp_in"), eb.get("snmp_in"), dt),
                    "snmp_out_bps": bps_from_delta(ea.get("snmp_out"), eb.get("snmp_out"), dt),
                    "gnmi_in_bps": bps_from_delta(ea.get("gnmi_in"), eb.get("gnmi_in"), dt),
                    "gnmi_out_bps": bps_from_delta(ea.get("gnmi_out"), eb.get("gnmi_out"), dt),
                }
                # consistency CLI vs SNMP vs gNMI
                for direction in ("in", "out"):
                    cli = row[f"cli_{direction}_bps"]
                    snmp = row[f"snmp_{direction}_bps"]
                    gnmi = row[f"gnmi_{direction}_bps"]
                    row[f"snmp_vs_cli_{direction}_pct"] = pct_diff(cli, snmp)
                    row[f"gnmi_vs_cli_{direction}_pct"] = pct_diff(cli, gnmi)
                comparisons.append(row)

    # PromQL: dashboard-style rates for matching devices/ifaces
    prom_rows: list[dict] = []
    # Discover label names
    for window_sec in (60, 90, 120, 300):
        q = (
            f'sum by (device_name, if_interface_name) '
            f'(rate(kentik_snmp_ifHCInOctets{{device_name=~"leaf1|leaf2|spine1"}}[{window_sec}s])) * 8'
        )
        try:
            data = prom_query(prom_url, prom_user, prom_token, q)
            for r in data.get("data", {}).get("result", []):
                prom_rows.append(
                    {
                        "window": f"{window_sec}s",
                        "direction": "in",
                        "device": r["metric"].get("device_name"),
                        "iface": r["metric"].get("if_interface_name"),
                        "prom_bps": float(r["value"][1]),
                        "query": "rate(ifHCInOctets)*8",
                    }
                )
        except Exception as e:
            prom_rows.append({"window": f"{window_sec}s", "direction": "in", "error": str(e)})

        q = (
            f'sum by (device_name, if_interface_name) '
            f'(rate(kentik_snmp_ifHCOutOctets{{device_name=~"leaf1|leaf2|spine1"}}[{window_sec}s])) * 8'
        )
        try:
            data = prom_query(prom_url, prom_user, prom_token, q)
            for r in data.get("data", {}).get("result", []):
                prom_rows.append(
                    {
                        "window": f"{window_sec}s",
                        "direction": "out",
                        "device": r["metric"].get("device_name"),
                        "iface": r["metric"].get("if_interface_name"),
                        "prom_bps": float(r["value"][1]),
                        "query": "rate(ifHCOutOctets)*8",
                    }
                )
        except Exception as e:
            prom_rows.append({"window": f"{window_sec}s", "direction": "out", "error": str(e)})

    # Also try gnmi metric names
    gnmi_metric_probe = prom_query(
        prom_url,
        prom_user,
        prom_token,
        'count by (__name__) ({__name__=~"(?i).*octet.*", service_name="gnmic"})',
    )

    # Join last window CLI rates with prom 90s/120s
    last = [c for c in comparisons if c["window"] == f"s{NUM_SAMPLES-1}-s{NUM_SAMPLES}"]
    joined: list[dict] = []
    for c in last:
        for direction in ("in", "out"):
            cli = c[f"cli_{direction}_bps"]
            snmp = c[f"snmp_{direction}_bps"]
            gnmi = c[f"gnmi_{direction}_bps"]
            # match prom rows for same device/iface/direction at 120s
            matches = [
                p
                for p in prom_rows
                if p.get("device") == c["device"]
                and p.get("iface") == c["iface"]
                and p.get("direction") == direction
                and p.get("window") == "120s"
            ]
            prom = matches[0]["prom_bps"] if matches else None
            joined.append(
                {
                    "device": c["device"],
                    "iface": c["iface"],
                    "direction": direction,
                    "dt_sec": c["dt_sec"],
                    "cli_bps": cli,
                    "snmp_bps": snmp,
                    "gnmi_bps": gnmi,
                    "prom_rate_120s_bps": prom,
                    "snmp_vs_cli_pct": pct_diff(cli, snmp),
                    "gnmi_vs_cli_pct": pct_diff(cli, gnmi),
                    "prom_vs_cli_pct": pct_diff(cli, prom),
                    "prom_vs_snmp_pct": pct_diff(snmp, prom),
                }
            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "sample_gap_sec": SAMPLE_GAP_SEC,
            "num_samples": NUM_SAMPLES,
            "snmp_poll_sec": 60,
            "gnmi_sample_sec": 30,
            "dashboard_query": "rate(kentik_snmp_ifHCIn/OutOctets[$__rate_interval]) * 8",
            "traffic": "iperf3 client2→client1 ~10 Mbps (scripts/traffic.sh)",
        },
        "samples": samples,
        "rate_windows": comparisons,
        "prom_rows": prom_rows,
        "gnmi_metric_probe": gnmi_metric_probe,
        "joined_last_window": joined,
    }

    out_path = ROOT / ".dash-payloads" / "iface-bps-validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {out_path}")

    print("\n=== LAST WINDOW vs PROM (120s rate*8) ===")
    print(
        f"{'device':8} {'iface':14} {'dir':3} {'cli':>10} {'snmp':>10} {'gnmi':>10} {'prom120':>10} "
        f"{'snmp%cli':>8} {'gnmi%cli':>8} {'prom%cli':>8}"
    )
    for j in joined:
        def fmt(v):
            return f"{v:,.0f}" if isinstance(v, (int, float)) and v is not None else "-"

        def fmtp(v):
            return f"{v:+.1f}%" if isinstance(v, (int, float)) and v is not None else "-"

        print(
            f"{j['device']:8} {j['iface']:14} {j['direction']:3} "
            f"{fmt(j['cli_bps']):>10} {fmt(j['snmp_bps']):>10} {fmt(j['gnmi_bps']):>10} "
            f"{fmt(j['prom_rate_120s_bps']):>10} "
            f"{fmtp(j['snmp_vs_cli_pct']):>8} {fmtp(j['gnmi_vs_cli_pct']):>8} {fmtp(j['prom_vs_cli_pct']):>8}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
