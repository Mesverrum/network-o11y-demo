#!/usr/bin/env python3
"""Sanity-check Network Flow Summary counting against the local lab.

Compares dashboard-style PromQL (series count, byte rates, top conversations)
to softflowd/ktranslate path health and optional controlled iperf burst.

Usage:
  python3 local/scripts/validate-flow-counts.py
  python3 local/scripts/validate-flow-counts.py --burst   # run 15s UDP burst first
  python3 local/scripts/validate-flow-counts.py --wait 90 # seconds after burst before query

Requires: lab up, softflowd (make softflowd), traffic (make traffic).
Prometheus: GRAFANA_URL + GRAFANA_TOKEN in local/.env, or GCX_CONTEXT for gcx api.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Steady lab traffic from scripts/traffic.sh (approximate application-layer targets)
EXPECTED_STEADY_BPS = {
    "client2_to_client1_udp": 3_000_000,
    "client1_to_client2_udp": 1_000_000,
    "icmp_chatter": 50_000,  # ping 1/s — order-of-magnitude
}
EXPECTED_STEADY_TOTAL_BPS = sum(EXPECTED_STEADY_BPS.values())

# ktranslate NetFlow rollup interval (seconds)
ROLLUP_SEC = 60

_DOCKER_PREFIX: list[str] | None = None


def docker_cmd() -> list[str]:
    """Use WSL docker on Windows hosts (lab containers live in WSL); native docker elsewhere."""
    global _DOCKER_PREFIX
    if _DOCKER_PREFIX is not None:
        return _DOCKER_PREFIX
    candidates: list[list[str]] = []
    if platform.system() == "Windows":
        candidates.append(["wsl", "-e", "docker"])
    candidates.append(["docker"])
    for prefix in candidates:
        r = subprocess.run(
            [*prefix, "inspect", "ktranslate_flow"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            _DOCKER_PREFIX = prefix
            return _DOCKER_PREFIX
    _DOCKER_PREFIX = ["docker"]
    return _DOCKER_PREFIX


def sh(cmd: list[str], timeout: int = 120) -> str:
    if cmd and cmd[0] == "docker":
        cmd = [*docker_cmd(), *cmd[1:]]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and not out.strip():
        out = f"exit {r.returncode}"
    return out.strip()


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    dotenv = ROOT / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def find_gcx() -> Path | None:
    if platform.system() == "Linux":
        names = ("gcx",)
    else:
        names = ("gcx.exe", "gcx")
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def prom_via_http(env: dict[str, str], expr: str) -> list[dict]:
    base = env.get("GRAFANA_URL", "").rstrip("/")
    token = env.get("GRAFANA_TOKEN", "")
    if not base or not token:
        return []
    q = urllib.parse.urlencode({"query": expr})
    url = f"{base}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data.get("data", {}).get("result", [])


def prom_via_gcx(context: str, expr: str) -> list[dict]:
    gcx = find_gcx()
    if not gcx:
        return []
    path = f"/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{urllib.parse.urlencode({'query': expr})}"
    cmd = [str(gcx), "--context", context, "--agent", "api", path, "-o", "json"]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    start = out.find("{")
    if start < 0:
        return []
    data = json.loads(out[start:])
    return data.get("data", {}).get("result", [])


def prom_query(env: dict[str, str], expr: str) -> list[dict]:
    rows = prom_via_http(env, expr)
    if rows:
        return rows
    ctx = env.get("GCX_CONTEXT", "networko11ydev")
    return prom_via_gcx(ctx, expr)


def scalar(rows: list[dict]) -> float | None:
    if not rows:
        return None
    try:
        return float(rows[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def check_local_path() -> dict:
    issues: list[str] = []
    kt_ip = sh(
        [
            "docker",
            "inspect",
            "-f",
            '{{(index .NetworkSettings.Networks "clab").IPAddress}}',
            "ktranslate_flow",
        ]
    )
    if not kt_ip or "Error" in kt_ip:
        issues.append("ktranslate_flow not on clab network")

    softflowd: dict[str, str] = {}
    for c in ("client1", "client2"):
        ps = sh(["docker", "exec", c, "sh", "-c", "pgrep -a softflowd 2>/dev/null || true"])
        softflowd[c] = ps or "(not running)"
        if not ps or "softflowd" not in ps:
            issues.append(f"{c}: softflowd not running - run: make -C local softflowd")

    traffic = sh(["docker", "exec", "client2", "sh", "-c", "pgrep -c iperf3 2>/dev/null || echo 0"])
    return {
        "ktranslate_flow_ip": kt_ip,
        "softflowd": softflowd,
        "client2_iperf3_procs": traffic,
        "issues": issues,
    }


def run_burst() -> None:
    print("==> Controlled burst: client2 -> client1 UDP 5 Mbps for 15s")
    sh(
        [
            "docker",
            "exec",
            "client2",
            "sh",
            "-c",
            "iperf3 -c 172.17.0.1 -p 5201 -u -b 5M -t 15 -l 1200 >/tmp/flow-validate-burst.log 2>&1",
        ],
        timeout=30,
    )
    for c in ("client1", "client2"):
        sh(["docker", "exec", c, "softflowctl", "expire-all"], timeout=15)


def extract_dashboard_exprs() -> list[str]:
    gcx = find_gcx()
    if not gcx:
        return []
    try:
        out = subprocess.check_output(
            [str(gcx), "--context", "networko11ydev", "--agent", "dashboards", "get", "lab-ktranslate-flow", "-o", "json"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        start = out.find("{")
        if start < 0:
            return []
        blob = json.dumps(json.loads(out[start:]))
        return sorted(set(re.findall(r'"expr":"([^"]+)"', blob)))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


def pct_delta(observed: float, expected: float) -> float:
    if expected <= 0:
        return 0.0
    return abs(observed - expected) / expected * 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--burst", action="store_true", help="run controlled iperf burst before querying")
    parser.add_argument("--wait", type=int, default=75, help="seconds to wait for ktranslate rollup (default 75)")
    args = parser.parse_args()

    env = load_env()
    print("=== Local path ===")
    path = check_local_path()
    print(json.dumps(path, indent=2))
    if path["issues"]:
        print("\nFIX first:")
        for i in path["issues"]:
            print(f"  - {i}")
        return 1

    if args.burst:
        run_burst()
        print(f"==> Waiting {args.wait}s for ktranslate rollup...")
        time.sleep(args.wait)
    else:
        print(f"==> Using current traffic (no burst). Querying after {min(args.wait, 10)}s settle...")
        time.sleep(min(args.wait, 10))

    print("\n=== Dashboard-style PromQL (lab-ktranslate-flow / 02. Network Flow Summary) ===")
    queries = {
        "active_flow_series": "count(network_io_by_flow_bytes)",
        "total_bps_5m": "sum(rate(network_io_by_flow_bytes[5m]))",
        "total_bps_gauge_60s": "sum(network_io_by_flow_bytes) * 8 / 60",
        "bps_by_exporter": "sum by (device_name) (rate(network_io_by_flow_bytes[5m]))",
        "bps_by_exporter_gauge_60s": "sum by (device_name) (network_io_by_flow_bytes) * 8 / 60",
        "lab_subnet_series": (
            'count(network_io_by_flow_bytes{network_local_address=~"172.17.0.*"})'
            ' or count(network_io_by_flow_bytes{network_peer_address=~"172.17.0.*"})'
        ),
        "top_conversations": "topk(10, network_io_by_flow_bytes)",
    }

    results: dict[str, object] = {}
    for name, expr in queries.items():
        rows = prom_query(env, expr)
        results[name] = {"expr": expr, "n": len(rows), "rows": rows[:12]}
        if name == "active_flow_series":
            print(f"{name}: {scalar(rows)} series")
        elif name == "total_bps_5m":
            bps = scalar(rows)
            print(f"{name}: {bps:,.0f} bps" if bps is not None else f"{name}: (no data)")
        elif name == "total_bps_gauge_60s":
            bps = scalar(rows)
            print(f"{name}: {bps:,.0f} bps (ktranslate rollup gauge * 8 / 60)" if bps is not None else f"{name}: (no data)")
        elif name == "bps_by_exporter":
            for r in rows:
                print(f"  {r.get('metric', {})}: {float(r['value'][1]):,.0f} bps")
        elif name == "bps_by_exporter_gauge_60s":
            for r in rows:
                print(f"  {r.get('metric', {})}: {float(r['value'][1]):,.0f} bps (gauge)")
        elif name == "lab_subnet_series":
            print(f"{name}: {scalar(rows)} series")
        elif name == "top_conversations":
            print(f"{name}: showing {min(len(rows), 5)} of {len(rows)}")
            for r in rows[:5]:
                m = r.get("metric", {})
                labels = {k: m[k] for k in sorted(m) if k.startswith("network_") or k in ("device_name", "service_name")}
                print(f"  {labels} => {r['value'][1]}")

    series_n = scalar(results["active_flow_series"]["rows"])  # type: ignore[index]
    total_bps = scalar(results["total_bps_5m"]["rows"])  # type: ignore[index]
    total_bps_gauge = scalar(results["total_bps_gauge_60s"]["rows"])  # type: ignore[index]

    print("\n=== Sanity verdict ===")
    verdicts: list[str] = []
    if series_n is None or series_n < 1:
        verdicts.append("FAIL: no network_io_by_flow_bytes series - check softflowd -> ktranslate_flow:9995 -> Alloy OTLP")
    else:
        verdicts.append(f"OK: {int(series_n)} active flow series in Prometheus")

    if total_bps_gauge is not None and total_bps_gauge > 0:
        delta = pct_delta(total_bps_gauge, EXPECTED_STEADY_TOTAL_BPS)
        verdicts.append(
            f"gauge total {total_bps_gauge:,.0f} bps vs ~{EXPECTED_STEADY_TOTAL_BPS:,} bps steady lab (delta {delta:.0f}%)"
        )
        if delta <= 50:
            verdicts.append("OK: gauge byte math plausible for make traffic (3M+1M UDP + ping)")
        else:
            verdicts.append("WARN: gauge total far from baseline - check traffic or rollup window")
    elif total_bps is not None and total_bps > 0:
        delta = pct_delta(total_bps, EXPECTED_STEADY_TOTAL_BPS)
        verdicts.append(
            f"rate() total {total_bps:,.0f} bps vs ~{EXPECTED_STEADY_TOTAL_BPS:,} bps expected steady lab (delta {delta:.0f}%)"
        )
        if delta > 80:
            verdicts.append("WARN: rate() under-reports if network_io_by_flow_bytes is a rollup gauge - prefer gauge * 8 / 60")
        else:
            verdicts.append("OK: rate() total in plausible range")
    else:
        verdicts.append("WARN: zero flow byte rate - wait longer (--wait 90) or run --burst")

    dash_exprs = extract_dashboard_exprs()
    if dash_exprs:
        rate_exprs = [e for e in dash_exprs if "network_io_by_flow" in e and "rate(" in e]
        count_exprs = [e for e in dash_exprs if "count(" in e and "network_io_by_flow" in e]
        if rate_exprs:
            verdicts.append(f"Dashboard uses {len(rate_exprs)} rate(network_io_by_flow*) panel(s) - matches validation queries")
        if count_exprs:
            verdicts.append(f"Dashboard count panels: {count_exprs[:2]}")

    for v in verdicts:
        print(f"  {v}".encode("ascii", "replace").decode())

    out_path = ROOT / ".dash-payloads" / "flow-validate-report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "path": path,
        "queries": {k: {"expr": v["expr"], "n": v["n"]} for k, v in results.items()},  # type: ignore[union-attr]
        "series_count": series_n,
        "total_bps": total_bps,
        "total_bps_gauge_60s": total_bps_gauge,
        "expected_steady_bps": EXPECTED_STEADY_TOTAL_BPS,
        "verdicts": verdicts,
    }
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")

    return 0 if series_n and series_n >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
