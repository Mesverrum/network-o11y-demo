#!/usr/bin/env python3
"""Provision standard network-centric Grafana alert rules (ktranslate SNMP fleet).

Creates/updates rules in folder ``network-lab`` under rule group ``Network Lab / ktranslate``.

Usage:
  python3 local/scripts/provision-network-alerts.py --dry-run
  python3 local/scripts/provision-network-alerts.py
  python3 local/scripts/provision-network-alerts.py --delete
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES_JSON = ROOT / "fixtures" / "network-alert-rules.json"
FOLDER_UID = "network-lab"
RULE_GROUP = "Network Lab / ktranslate"
PROM_DS = "grafanacloud-prom"
ORG_ID = 1
DASH_UID = "ktranslate-device-summary"
DETAIL_UID = "ktranslate-device-details"


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


def slug_uid(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"net-{slug[:36]}"


def prom_query(ref_id: str, expr: str, *, instant: bool = True) -> dict[str, Any]:
    return {
        "refId": ref_id,
        "queryType": "",
        "relativeTimeRange": {"from": 600, "to": 0},
        "datasourceUid": PROM_DS,
        "model": {
            "datasource": {"type": "prometheus", "uid": PROM_DS},
            "expr": expr,
            "instant": instant,
            "intervalMs": 1000,
            "legendFormat": "__auto",
            "maxDataPoints": 43200,
            "refId": ref_id,
        },
    }


def threshold_condition(ref_id: str, input_ref: str, op: str, value: float) -> dict[str, Any]:
    return {
        "refId": ref_id,
        "queryType": "",
        "relativeTimeRange": {"from": 0, "to": 0},
        "datasourceUid": "__expr__",
        "model": {
            "conditions": [
                {
                    "evaluator": {"params": [value], "type": op},
                    "operator": {"type": "and"},
                    "query": {"params": [input_ref]},
                    "reducer": {"params": [], "type": "last"},
                    "type": "query",
                }
            ],
            "datasource": {"type": "__expr__", "uid": "__expr__"},
            "expression": "",
            "intervalMs": 1000,
            "maxDataPoints": 43200,
            "refId": ref_id,
            "type": "classic_conditions",
        },
    }


def build_rule(defn: dict[str, Any], *, grafana_url: str) -> dict[str, Any]:
    expr = defn["expr"]
    threshold = defn.get("threshold", 0)
    op = defn.get("op", "gt")
    return {
        "uid": defn["uid"],
        "title": defn["title"],
        "condition": "B",
        "data": [
            prom_query("A", expr, instant=defn.get("instant", True)),
            threshold_condition("B", "A", op, threshold),
        ],
        "noDataState": defn.get("noDataState", "OK"),
        "execErrState": defn.get("execErrState", "Error"),
        "for": defn.get("for", "5m"),
        "annotations": {
            "summary": defn["summary"],
            "description": defn.get("description", defn["summary"]),
            "runbook_url": defn.get(
                "runbook_url",
                f"{grafana_url.rstrip('/')}/d/{DASH_UID}/03-network-device-summary",
            ),
        },
        "labels": {
            "category": "network",
            "source": "ktranslate",
            "severity": defn["severity"],
            **defn.get("labels", {}),
        },
        "isPaused": defn.get("isPaused", False),
    }


def rule_definitions(grafana_url: str = "") -> list[dict[str, Any]]:
    mem_pct = "kentik_snmp_MemoryUtilization"
    iface_err_rate = (
        "sum by(device_name, if_interface_name) ("
        "(kentik_snmp_ifInErrors) / 60 + (kentik_snmp_ifOutErrors) / 60)"
    )
    specs = [
        {
            "title": "BGP session not established",
            "expr": 'kentik_snmp_tBgpPeerNgConnState{tBgpPeerNgConnState!="established"}',
            "for": "5m",
            "severity": "warning",
            "summary": "BGP peer {{ $labels.device_name }} group {{ $labels.peer_group }} AS {{ $labels.peer_as }} is {{ $labels.tBgpPeerNgConnState }}",
            "description": "BGP ConnState is not established for 5 minutes.",
            "labels": {"domain": "routing"},
        },
        {
            "title": "SNMP polling unhealthy",
            "expr": "kentik_snmp_PollingHealth != 1",
            "for": "10m",
            "severity": "critical",
            "summary": "SNMP polling unhealthy on {{ $labels.device_name }} ({{ $labels.PollingHealth }})",
            "description": "ktranslate PollingHealth is not GOOD for 10 minutes.",
            "labels": {"domain": "collection"},
        },
        {
            "title": "Interface admin-up oper-down",
            "expr": 'kentik_snmp_if_OperStatus{if_AdminStatus="up",if_OperStatus="down"}',
            "for": "5m",
            "severity": "warning",
            "summary": "Interface {{ $labels.if_interface_name }} on {{ $labels.device_name }} is oper-down",
            "description": "Admin-up interface has been oper-down for 5 minutes.",
            "labels": {"domain": "interfaces"},
        },
        {
            "title": "High interface error rate",
            "expr": f"{iface_err_rate} > 5",
            "for": "10m",
            "severity": "warning",
            "summary": "High errors on {{ $labels.device_name }} {{ $labels.if_interface_name }}",
            "description": "Combined in+out errors exceed 5/s (ktranslate 60s delta gauge).",
            "labels": {"domain": "interfaces"},
        },
        {
            "title": "High device CPU",
            "expr": "max by(device_name) (kentik_snmp_CPU) > 85",
            "for": "15m",
            "severity": "warning",
            "summary": "CPU above 85% on {{ $labels.device_name }}",
            "description": "Device CPU has been above 85% for 15 minutes.",
            "labels": {"domain": "resources"},
        },
        {
            "title": "High device memory",
            "expr": f"max by(device_name) ({mem_pct}) > 90",
            "for": "15m",
            "severity": "warning",
            "summary": "Memory above 90% on {{ $labels.device_name }}",
            "description": "Memory utilization from ktranslate MemoryUtilization (MemoryUsed + MemoryFree).",
            "labels": {"domain": "resources"},
        },
        {
            "title": "Chassis fan not in service",
            "expr": (
                'kentik_snmp_tmnxPhysChassisFanOperStatus'
                '{tmnxPhysChassisFanOperStatus!="deviceStateInService"}'
            ),
            "for": "2m",
            "severity": "critical",
            "summary": "Fan issue on {{ $labels.device_name }} slot {{ $labels.Index }} ({{ $labels.tmnxPhysChassisFanOperStatus }})",
            "description": "Chassis fan oper status is not in service.",
            "labels": {"domain": "hardware"},
        },
        {
            "title": "Power supply failed or degraded",
            "expr": (
                "kentik_snmp_tmnxPhysChassisPMOutputStatus"
                '{tmnxPhysChassisPMOutputStatus=~"failed|outOfService|degraded"}'
            ),
            "for": "2m",
            "severity": "critical",
            "summary": "PSU issue on {{ $labels.device_name }} slot {{ $labels.Index }} ({{ $labels.tmnxPhysChassisPMOutputStatus }})",
            "description": "Power supply output status is failed, out of service, or degraded.",
            "labels": {"domain": "hardware"},
        },
        {
            "title": "Hardware FRU not in service",
            "expr": (
                "kentik_snmp_tmnxHwOperState"
                '{tmnxHwOperState=~"failed|outOfService|diagnosing|resetPending"}'
            ),
            "for": "5m",
            "severity": "critical",
            "summary": "FRU {{ $labels.hw_name }} on {{ $labels.device_name }} is {{ $labels.tmnxHwOperState }}",
            "description": "Chassis hardware component is not in service.",
            "labels": {"domain": "hardware"},
        },
        {
            "title": "High chassis temperature",
            "expr": "max by(device_name) (kentik_snmp_tmnxHwTemperature) > 75",
            "for": "10m",
            "severity": "warning",
            "summary": "High temperature on {{ $labels.device_name }}",
            "description": "Max chassis/sensor temperature exceeds 75°C for 10 minutes.",
            "labels": {"domain": "hardware"},
        },
        {
            "title": "SNMP collector heartbeat missing",
            "expr": (
                "(count(count by(service_name) ("
                'kentik_ktranslate_chf_kkc_jchfq{service_name=~"ktranslate-snmp.*"}'
                ")) or on() vector(0)) < 1"
            ),
            "for": "5m",
            "severity": "critical",
            "summary": "No ktranslate SNMP collector CHF heartbeat detected",
            "description": "Fleet has zero active ktranslate-snmp CHF heartbeats for 5 minutes.",
            "labels": {"domain": "collection"},
            "noDataState": "OK",
        },
        {
            "title": "Elevated SNMP trap rate",
            "expr": (
                'sum(rate(kentik_ktranslate_chf_kkc_snmp_traps{service_name=~"ktranslate-snmp.*"}[5m])) > 0.5'
            ),
            "for": "5m",
            "severity": "info",
            "summary": "Elevated SNMP trap rate across ktranslate SNMP collectors",
            "description": "Fleet trap rate exceeds 0.5/s for 5 minutes.",
            "labels": {"domain": "events"},
            "instant": False,
        },
    ]
    rules: list[dict[str, Any]] = []
    for spec in specs:
        uid = spec.get("uid") or slug_uid(spec["title"])
        rules.append(build_rule({**spec, "uid": uid}, grafana_url=grafana_url))
    return rules


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


def export_rules(path: Path, *, grafana_url: str = "") -> None:
    payload = {
        "folderUID": FOLDER_UID,
        "ruleGroup": RULE_GROUP,
        "interval": "1m",
        "rules": rule_definitions(grafana_url),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def provision(env: dict[str, str], *, dry_run: bool = False) -> None:
    grafana_url = env["GRAFANA_URL"]
    rules = rule_definitions(grafana_url)
    export_rules(RULES_JSON, grafana_url=grafana_url)
    body = {
        "title": RULE_GROUP,
        "interval": 60,
        "rules": rules,
    }
    path = f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{urllib.parse.quote(RULE_GROUP, safe='')}"
    if dry_run:
        print(f"dry-run: would PUT {path} with {len(rules)} rules")
        for rule in rules:
            print(f"  - {rule['uid']}: {rule['title']} [{rule['labels']['severity']}]")
        print(f"Wrote {RULES_JSON}")
        return

    status, out = http_json(env, "PUT", path, body)
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT rule group -> {status}: {out}")
    print(f"Provisioned {len(rules)} rules in folder {FOLDER_UID} / {RULE_GROUP}")
    for rule in rules:
        print(f"  - {rule['uid']}: {rule['title']}")


def delete_rules(env: dict[str, str]) -> None:
    path = f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{urllib.parse.quote(RULE_GROUP, safe='')}"
    status, out = http_json(env, "DELETE", path)
    if status not in (200, 202, 204, 404):
        raise RuntimeError(f"DELETE rule group -> {status}: {out}")
    print(f"Deleted rule group {RULE_GROUP} (status {status})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete", action="store_true", help="Remove the rule group")
    ap.add_argument("--export-only", action="store_true", help="Write fixtures JSON only")
    args = ap.parse_args()

    if args.export_only:
        export_rules(RULES_JSON)
        print(f"Wrote {RULES_JSON}")
        return 0

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    if args.delete:
        if args.dry_run:
            print(f"dry-run: would DELETE {RULE_GROUP}")
            return 0
        delete_rules(env)
        return 0

    provision(env, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
