#!/usr/bin/env python3
"""Provision Grafana-managed recording rules for Alloy SNMP composites.

Colon names follow Prometheus ``level:metric:operations`` so they cannot collide
with scrape metrics. Formulas match ktranslate's computed exports:

  MemoryUtilization   Used/(Used+Free), else Total variants, else vendor %
  ifInErrorPercent    errors / unicast_pkts * 100  (ucast > 0)
  ifHC*Octets rate    Alloy equivalent of ktranslate delta gauges / poll_sec
  IfInUtilization     (octets*8) / (ifHighSpeed_Mbps * 1e6)

Usage:
  python3 local/scripts/provision-alloy-snmp-recording-rules.py --dry-run
  python3 local/scripts/provision-alloy-snmp-recording-rules.py
  python3 local/scripts/provision-alloy-snmp-recording-rules.py --delete
"""
from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
YAML_OUT = ROOT / "fixtures" / "alloy-snmp" / "recording-rules.yaml"
FOLDER_UID = "network-lab"
RULE_GROUP_HOT = "Network Lab / alloy-snmp composites"
RULE_GROUP_COLD = "Network Lab / alloy-snmp composites cold"
# Packet-derived rules evaluate at cold scrape cadence (5m lab / not 60s).
INTERVAL_HOT_SEC = 60
INTERVAL_COLD_SEC = 300
PROM_DS = "grafanacloud-prom"
JOB = 'job="alloy-snmp"'
# Interface joins drop cold-tier extras (if_Description, if_MAC, if_Type, …).
# Hot and cold scrapes use different Alloy `instance` values — never match on it
# across tiers (octets=hot, errors+unicast pkts=cold).
IF_ON_HOT = "instance, device_name, job, snmp_group, ifIndex, if_interface_name"
IF_ON_CROSS = "device_name, job, snmp_group, ifIndex, if_interface_name"
DEV_BY = "instance, device_name, job, snmp_group"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _mem_percent() -> str:
    # ktranslate device_metrics.go order, then vendor-native percent OIDs.
    # max by() so `or` precedence works (same label set).
    vendor = " or ".join(
        [
            f"snmp_cseSysMemoryUtilization{{{JOB}}}",
            f"snmp_wlsxSysExtMemoryUsedPercent{{{JOB}}}",
            f"snmp_perCentMemoryUtilization{{{JOB}}}",
            f"snmp_tpSysMonitorMemoryUtilization{{{JOB}}}",
            f"snmp_sfosMemoryPercentUsage{{{JOB}}}",
            f"snmp_jnxOperatingBuffer{{{JOB}}}",
            f"snmp_hwEntityMemUsage{{{JOB}}}",
            f"snmp_hh3cEntityExtMemUsage{{{JOB}}}",
            f"snmp_ramUtilization{{{JOB}}}",
            f"snmp_swMemUsage{{{JOB}}}",
            f"snmp_genMemUtilizationPercentUsed{{{JOB}}}",
            f"snmp_iveMemoryUtil{{{JOB}}}",
            f"snmp_sonicCurrentRAMUtil{{{JOB}}}",
            f"snmp_chStackUnitMemUsageUtil{{{JOB}}}",
            f"snmp_ibSystemMonitorMemUsage{{{JOB}}}",
            f"snmp_sysMgmtMemUsage{{{JOB}}}",
        ]
    )
    used = f"snmp_MemoryUsed{{{JOB}}}"
    free = f"snmp_MemoryFree{{{JOB}}}"
    total = f"snmp_MemoryTotal{{{JOB}}}"
    computed = f"""
              100 * {used} / ({used} + {free})
            or
              100 * ({total} - {free}) / {total}
            or
              100 * {used} / {total}
"""
    return f"""
max by ({DEV_BY}) (
  {vendor}
)
or
max by ({DEV_BY}) (
{computed}
)
""".strip()


def _err_percent(direction: str) -> str:
    errors = f"snmp_if{direction}Errors{{{JOB}}}"
    pkts = f"snmp_ifHC{direction}UcastPkts{{{JOB}}}"
    # Packets + errors live on the cold scrape (~5m). [15m] so rate() sees two samples.
    # ktranslate: ifInErrorPercent = ifInErrors / ifHCInUcastPkts * 100 when pkts > 0
    return f"""
(
  100 * rate({errors}[15m])
    / on({IF_ON_CROSS}) group_left()
      rate({pkts}[15m])
)
and on({IF_ON_CROSS})
  (rate({pkts}[15m]) > 0)
""".strip()


def _util_percent(direction: str) -> str:
    octets = f"snmp_ifHC{direction}Octets{{{JOB}}}"
    speed = f"snmp_ifHighSpeed{{{JOB}}}"
    # ifHighSpeed is 0 on mgmt / unnumbered — skip those (avoid +Inf).
    return f"""
100 * rate({octets}[5m]) * 8
  / on({IF_ON_HOT}) group_left()
    (({speed} > 0) * 1e6)
""".strip()


def rule_specs() -> list[dict[str, str]]:
    return [
        {
            "uid": "rr-alloy-snmp-memory-util",
            "title": "Alloy SNMP memory utilization %",
            "record": "device:snmp_MemoryUtilization:percent",
            "tier": "hot",
            "expr": _mem_percent(),
        },
        {
            "uid": "rr-alloy-snmp-ifin-err-rate",
            "title": "Alloy SNMP ifInErrors rate",
            "record": "if:snmp_ifInErrors:rate5m",
            "tier": "cold",
            "expr": f"rate(snmp_ifInErrors{{{JOB}}}[15m])",
        },
        {
            "uid": "rr-alloy-snmp-ifout-err-rate",
            "title": "Alloy SNMP ifOutErrors rate",
            "record": "if:snmp_ifOutErrors:rate5m",
            "tier": "cold",
            "expr": f"rate(snmp_ifOutErrors{{{JOB}}}[15m])",
        },
        {
            "uid": "rr-alloy-snmp-ifin-err-pct",
            "title": "Alloy SNMP ifInErrorPercent",
            "record": "if:snmp_ifInErrorPercent:percent",
            "tier": "cold",
            "expr": _err_percent("In"),
        },
        {
            "uid": "rr-alloy-snmp-ifout-err-pct",
            "title": "Alloy SNMP ifOutErrorPercent",
            "record": "if:snmp_ifOutErrorPercent:percent",
            "tier": "cold",
            "expr": _err_percent("Out"),
        },
        {
            "uid": "rr-alloy-snmp-ifin-octets-rate",
            "title": "Alloy SNMP ifHCInOctets rate",
            "record": "if:snmp_ifHCInOctets:rate5m",
            "tier": "hot",
            "expr": f"rate(snmp_ifHCInOctets{{{JOB}}}[5m])",
        },
        {
            "uid": "rr-alloy-snmp-ifout-octets-rate",
            "title": "Alloy SNMP ifHCOutOctets rate",
            "record": "if:snmp_ifHCOutOctets:rate5m",
            "tier": "hot",
            "expr": f"rate(snmp_ifHCOutOctets{{{JOB}}}[5m])",
        },
        {
            "uid": "rr-alloy-snmp-ifin-util",
            "title": "Alloy SNMP IfInUtilization %",
            "record": "if:snmp_IfInUtilization:percent",
            "tier": "hot",
            "expr": _util_percent("In"),
        },
        {
            "uid": "rr-alloy-snmp-ifout-util",
            "title": "Alloy SNMP IfOutUtilization %",
            "record": "if:snmp_IfOutUtilization:percent",
            "tier": "hot",
            "expr": _util_percent("Out"),
        },
    ]


def grafana_rule(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "uid": spec["uid"],
        "title": spec["title"],
        "for": "0s",
        "orgId": 1,
        "labels": {
            "source": "alloy-snmp",
            "kind": "composite",
            "snmp_eval_tier": spec.get("tier", "hot"),
        },
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 1800, "to": 0},
                "datasourceUid": PROM_DS,
                "model": {
                    "datasource": {"type": "prometheus", "uid": PROM_DS},
                    "expr": spec["expr"],
                    "instant": True,
                    "intervalMs": 1000,
                    "legendFormat": "__auto",
                    "maxDataPoints": 43200,
                    "refId": "A",
                },
            }
        ],
        "record": {
            "metric": spec["record"],
            "from": "A",
            "target_datasource_uid": PROM_DS,
        },
        "isPaused": False,
    }


def _emit_yaml_group(
    lines: list[str],
    *,
    name: str,
    interval: str,
    specs: list[dict[str, str]],
) -> None:
    lines.append(f"  - name: {name}")
    lines.append(f"    interval: {interval}")
    lines.append("    rules:")
    for spec in specs:
        expr = spec["expr"].rstrip() + "\n"
        indented = "".join(
            ("          " + ln if ln.strip() else "\n") for ln in expr.splitlines(True)
        )
        lines.append(f"      - record: {spec['record']}")
        lines.append(f"        # {spec['title']}")
        lines.append("        expr: |")
        lines.append(indented.rstrip("\n"))
        lines.append("")


def export_yaml(specs: list[dict[str, str]]) -> None:
    hot = [s for s in specs if s.get("tier", "hot") == "hot"]
    cold = [s for s in specs if s.get("tier") == "cold"]
    lines = [
        "# Alloy SNMP composite recording rules.",
        "# Source of truth is provision-alloy-snmp-recording-rules.py (this file is exported).",
        "# Human catalog: docs/alloy-network-fork.md § Computed metrics (recording rules).",
        "#",
        "# Packet counters and interface errors are cold-tier scrapes — not a 60s problem.",
        "# Error rates and error % are recorded at 5m. Octets / link util stay at 1m.",
        "#",
        "# Load via Grafana-managed recording rules:",
        "#   python3 local/scripts/provision-alloy-snmp-recording-rules.py",
        "",
        "groups:",
    ]
    _emit_yaml_group(lines, name="alloy-snmp.composites", interval="1m", specs=hot)
    _emit_yaml_group(lines, name="alloy-snmp.composites.cold", interval="5m", specs=cold)
    YAML_OUT.parent.mkdir(parents=True, exist_ok=True)
    YAML_OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def http_json(
    env: dict[str, str],
    method: str,
    path: str,
    body: Any | None = None,
) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Disable-Provenance": "true",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:4000]}
        return exc.code, payload


def group_path(name: str) -> str:
    return (
        f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/"
        f"{urllib.parse.quote(name, safe='')}"
    )


def promql(env: dict[str, str], expr: str) -> list:
    base = env["GRAFANA_URL"].rstrip("/")
    q = urllib.parse.urlencode({"query": expr})
    url = f"{base}/api/datasources/proxy/uid/{PROM_DS}/api/v1/query?{q}"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        body = json.loads(resp.read().decode())
    if body.get("status") != "success":
        return []
    return body.get("data", {}).get("result") or []


def provision(env: dict[str, str], *, dry_run: bool = False) -> None:
    specs = rule_specs()
    export_yaml(specs)
    groups = [
        (RULE_GROUP_HOT, INTERVAL_HOT_SEC, [s for s in specs if s.get("tier", "hot") == "hot"]),
        (RULE_GROUP_COLD, INTERVAL_COLD_SEC, [s for s in specs if s.get("tier") == "cold"]),
    ]
    if dry_run:
        for title, interval, group_specs in groups:
            print(
                f"dry-run: would PUT {group_path(title)} "
                f"interval={interval}s rules={len(group_specs)}"
            )
            for spec in group_specs:
                print(f"  - {spec['record']}")
        print(f"Wrote {YAML_OUT}")
        return

    create_path = f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups"
    for title, interval, group_specs in groups:
        body = {
            "title": title,
            "interval": interval,
            "rules": [grafana_rule(s) for s in group_specs],
        }
        status, out = http_json(env, "PUT", group_path(title), body)
        if status == 404:
            status, out = http_json(env, "POST", create_path, body)
        if not (200 <= int(status) < 300):
            raise RuntimeError(f"PUT/POST {title} -> {status}: {out}")
        print(f"Provisioned {len(group_specs)} rules in {FOLDER_UID} / {title} ({interval}s)")
        for spec in group_specs:
            print(f"  - {spec['record']}")


def delete_rules(env: dict[str, str]) -> None:
    for title in (RULE_GROUP_HOT, RULE_GROUP_COLD):
        status, out = http_json(env, "DELETE", group_path(title))
        if status not in (200, 202, 204, 404):
            raise RuntimeError(f"DELETE {title} -> {status}: {out}")
        print(f"Deleted rule group {title} (status {status})")


def verify(env: dict[str, str], *, wait_sec: int = 0) -> None:
    if wait_sec:
        print(f"waiting {wait_sec}s for first evaluation…")
        time.sleep(wait_sec)
    for spec in rule_specs():
        name = spec["record"]
        rows = promql(env, f"count({name})")
        n = rows[0]["value"][1] if rows else "0"
        print(f"  {name}  series={n}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument(
        "--verify",
        action="store_true",
        help="Query recorded series after provision (optional --wait)",
    )
    ap.add_argument("--wait", type=int, default=0, help="Seconds to wait before --verify")
    args = ap.parse_args()

    specs = rule_specs()
    if args.export_only:
        export_yaml(specs)
        print(f"Wrote {YAML_OUT}")
        return 0

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    if args.delete:
        if args.dry_run:
            print(f"dry-run: would DELETE {RULE_GROUP_HOT} and {RULE_GROUP_COLD}")
            return 0
        delete_rules(env)
        return 0

    provision(env, dry_run=args.dry_run)
    if args.verify and not args.dry_run:
        verify(env, wait_sec=args.wait)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
