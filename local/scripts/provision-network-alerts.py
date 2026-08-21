#!/usr/bin/env python3
"""Provision standard network-centric Grafana alert rules.

ktranslate group: ``Network Lab / ktranslate`` (kentik_snmp_* / CHF).
Alloy group:      ``Network Lab / alloy`` (snmp_* / recording rules / Loki traps).

Per-device rules use Reduce (last, dropNN) + Threshold — not Classic Condition.
Classic Condition collapses every matching series into one instance and drops
query labels (``device_name``, ``if_interface_name``, ``peer_as``, …).

Usage:
  python3 local/scripts/provision-network-alerts.py --dry-run
  python3 local/scripts/provision-network-alerts.py
  python3 local/scripts/provision-network-alerts.py --alloy
  python3 local/scripts/provision-network-alerts.py --delete --alloy
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
RULES_JSON_ALLOY = ROOT / "fixtures" / "alloy-network-alert-rules.json"
FOLDER_UID = "network-lab"
RULE_GROUP = "Network Lab / ktranslate"
RULE_GROUP_ALLOY = "Network Lab / alloy"
PROM_DS = "grafanacloud-prom"
LOKI_DS = "grafanacloud-logs"
ORG_ID = 1
DASH_UID = "ktranslate-device-summary"
DETAIL_UID = "ktranslate-device-details"
DASH_UID_ALLOY = "alloy-flow-summary"
DETAIL_UID_ALLOY = "alloy-device-details"
JOB = 'job="alloy-snmp"'


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


def loki_query(ref_id: str, expr: str) -> dict[str, Any]:
    return {
        "refId": ref_id,
        "queryType": "",
        "relativeTimeRange": {"from": 600, "to": 0},
        "datasourceUid": LOKI_DS,
        "model": {
            "datasource": {"type": "loki", "uid": LOKI_DS},
            "editorMode": "code",
            "expr": expr,
            "instant": True,
            "intervalMs": 1000,
            "legendFormat": "",
            "maxDataPoints": 43200,
            "queryType": "instant",
            "refId": ref_id,
        },
    }


def reduce_expression(ref_id: str, input_ref: str) -> dict[str, Any]:
    """Last-per-series reduce. Classic Condition collapses all series and drops labels."""
    return {
        "refId": ref_id,
        "queryType": "",
        "relativeTimeRange": {"from": 0, "to": 0},
        "datasourceUid": "__expr__",
        "model": {
            "datasource": {"type": "__expr__", "uid": "__expr__"},
            "expression": input_ref,
            "intervalMs": 1000,
            "maxDataPoints": 43200,
            "reducer": "last",
            "refId": ref_id,
            "settings": {"mode": "dropNN"},
            "type": "reduce",
        },
    }


def threshold_expression(ref_id: str, input_ref: str, op: str, value: float) -> dict[str, Any]:
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
                    "query": {"params": [ref_id]},
                    "reducer": {"params": [], "type": "last"},
                    "type": "query",
                }
            ],
            "datasource": {"type": "__expr__", "uid": "__expr__"},
            "expression": input_ref,
            "intervalMs": 1000,
            "maxDataPoints": 43200,
            "refId": ref_id,
            "type": "threshold",
        },
    }


def build_rule(
    defn: dict[str, Any],
    *,
    grafana_url: str,
    source: str = "ktranslate",
    dash_uid: str = DASH_UID,
    detail_uid: str = DETAIL_UID,
) -> dict[str, Any]:
    expr = defn["expr"]
    threshold = defn.get("threshold", 0)
    op = defn.get("op", "gt")
    grafana = grafana_url.rstrip("/")
    if defn.get("per_device"):
        runbook = (
            f"{grafana}/d/{detail_uid}"
            "?var-instance={{ $labels.device_name }}"
        )
    else:
        runbook = f"{grafana}/d/{dash_uid}"
    query = (
        loki_query("A", expr)
        if defn.get("datasource") == "loki"
        else prom_query("A", expr, instant=defn.get("instant", True))
    )
    return {
        "uid": defn["uid"],
        "title": defn["title"],
        "condition": "C",
        "data": [
            query,
            reduce_expression("B", "A"),
            threshold_expression("C", "B", op, threshold),
        ],
        "noDataState": defn.get("noDataState", "OK"),
        "execErrState": defn.get("execErrState", "Error"),
        "for": defn.get("for", "5m"),
        "annotations": {
            "summary": defn["summary"],
            "description": defn.get("description", defn["summary"]),
            "runbook_url": defn.get("runbook_url", runbook),
        },
        "labels": {
            "category": "network",
            "source": source,
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
            "per_device": True,
        },
        {
            "title": "SNMP polling unhealthy",
            "expr": 'kentik_snmp_PollingHealth{PollingHealth!="GOOD"}',
            "for": "10m",
            "severity": "critical",
            "summary": "SNMP polling unhealthy on {{ $labels.device_name }} ({{ $labels.PollingHealth }})",
            "description": "ktranslate PollingHealth is not GOOD for 10 minutes.",
            "labels": {"domain": "collection"},
            "per_device": True,
        },
        {
            "title": "Interface admin-up oper-down",
            "expr": 'kentik_snmp_if_OperStatus{if_AdminStatus="up",if_OperStatus="down"}',
            "for": "5m",
            "severity": "warning",
            "summary": "Interface {{ $labels.if_interface_name }} on {{ $labels.device_name }} is oper-down",
            "description": "Admin-up interface has been oper-down for 5 minutes.",
            "labels": {"domain": "interfaces"},
            "per_device": True,
        },
        {
            "title": "High interface error rate",
            "expr": f"{iface_err_rate} > 5",
            "for": "10m",
            "severity": "warning",
            "summary": "High errors on {{ $labels.device_name }} {{ $labels.if_interface_name }}",
            "description": "Combined in+out errors exceed 5/s (ktranslate 60s delta gauge).",
            "labels": {"domain": "interfaces"},
            "per_device": True,
        },
        {
            "title": "High device CPU",
            "expr": "max by(device_name) (kentik_snmp_CPU) > 85",
            "for": "15m",
            "severity": "warning",
            "summary": "CPU above 85% on {{ $labels.device_name }}",
            "description": "Device CPU has been above 85% for 15 minutes.",
            "labels": {"domain": "resources"},
            "per_device": True,
        },
        {
            "title": "High device memory",
            "expr": f"max by(device_name) ({mem_pct}) > 90",
            "for": "15m",
            "severity": "warning",
            "summary": "Memory above 90% on {{ $labels.device_name }}",
            "description": "Memory utilization from ktranslate MemoryUtilization (MemoryUsed + MemoryFree).",
            "labels": {"domain": "resources"},
            "per_device": True,
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
            "per_device": True,
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
            "per_device": True,
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
            "per_device": True,
        },
        {
            "title": "High chassis temperature",
            "expr": "max by(device_name) (kentik_snmp_tmnxHwTemperature) > 75",
            "for": "10m",
            "severity": "warning",
            "summary": "High temperature on {{ $labels.device_name }}",
            "description": "Max chassis/sensor temperature exceeds 75°C for 10 minutes.",
            "labels": {"domain": "hardware"},
            "per_device": True,
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


def alloy_rule_definitions(grafana_url: str = "") -> list[dict[str, Any]]:
    """Parallel of the ktranslate group on Alloy scrape / recording-rule names.

    Enums are numeric on this path (snmp_exporter gauge + enum_values in YAML,
    no string label on the live series). TIMOS: BGP established=6, ifOper=2 down,
    ifAdmin=1 up, fan in-service=2, PSU failed/oos/degraded=4/5/6, FRU
    outOfService/diagnosing/failed/resetPending=3/4/5/14.
    """
    iface_err_rate = (
        "sum by(device_name, if_interface_name) ("
        "if:snmp_ifInErrors:rate5m + if:snmp_ifOutErrors:rate5m)"
    )
    oper_down = (
        f'(snmp_ifOperStatus{{{JOB}}} == 2) and on(device_name, ifIndex, if_interface_name) '
        f'(snmp_ifAdminStatus{{{JOB}}} == 1)'
    )
    specs = [
        {
            "uid": "na-bgp-session-not-established",
            "title": "Alloy: BGP session not established",
            "expr": f"snmp_tBgpPeerNgConnState{{{JOB}}} != 6",
            "for": "5m",
            "severity": "warning",
            "summary": "BGP peer {{ $labels.device_name }} group {{ $labels.peer_group }} AS {{ $labels.peer_as }} is not established",
            "description": "Alloy snmp_tBgpPeerNgConnState != 6 (TIMOS established) for 5 minutes.",
            "labels": {"domain": "routing"},
            "per_device": True,
        },
        {
            "uid": "na-snmp-polling-unhealthy",
            "title": "Alloy: SNMP polling unhealthy",
            "expr": f'max by(device_name) (up{{{JOB},snmp_tier="hot"}} == 0)',
            "for": "10m",
            "severity": "critical",
            "summary": "Alloy SNMP hot scrape down on {{ $labels.device_name }}",
            "description": "Alloy SNMP hot-tier up is 0 for 10 minutes. Replaces ktranslate PollingHealth.",
            "labels": {"domain": "collection"},
            "per_device": True,
        },
        {
            "uid": "na-interface-admin-up-oper-down",
            "title": "Alloy: Interface admin-up oper-down",
            "expr": oper_down,
            "for": "5m",
            "severity": "warning",
            "summary": "Interface {{ $labels.if_interface_name }} on {{ $labels.device_name }} is oper-down",
            "description": "Admin-up (ifAdminStatus=1) interface has been oper-down (ifOperStatus=2) for 5 minutes.",
            "labels": {"domain": "interfaces"},
            "per_device": True,
        },
        {
            "uid": "na-high-interface-error-rate",
            "title": "Alloy: High interface error rate",
            "expr": f"{iface_err_rate} > 5",
            "for": "10m",
            "severity": "warning",
            "summary": "High errors on {{ $labels.device_name }} {{ $labels.if_interface_name }}",
            "description": "Combined in+out error rate exceeds 5/s (Alloy recording rules if:snmp_if*Errors:rate5m).",
            "labels": {"domain": "interfaces"},
            "per_device": True,
        },
        {
            "uid": "na-high-device-cpu",
            "title": "Alloy: High device CPU",
            "expr": f"max by(device_name) (snmp_CPU{{{JOB}}}) > 85",
            "for": "15m",
            "severity": "warning",
            "summary": "CPU above 85% on {{ $labels.device_name }}",
            "description": "Device snmp_CPU has been above 85% for 15 minutes.",
            "labels": {"domain": "resources"},
            "per_device": True,
        },
        {
            "uid": "na-high-device-memory",
            "title": "Alloy: High device memory",
            "expr": "max by(device_name) (device:snmp_MemoryUtilization:percent) > 90",
            "for": "15m",
            "severity": "warning",
            "summary": "Memory above 90% on {{ $labels.device_name }}",
            "description": "Memory utilization from Alloy recording rule device:snmp_MemoryUtilization:percent.",
            "labels": {"domain": "resources"},
            "per_device": True,
        },
        {
            "uid": "na-chassis-fan-not-in-service",
            "title": "Alloy: Chassis fan not in service",
            "expr": f"snmp_tmnxPhysChassisFanOperStatus{{{JOB}}} != 2",
            "for": "2m",
            "severity": "critical",
            "summary": "Fan issue on {{ $labels.device_name }}",
            "description": "snmp_tmnxPhysChassisFanOperStatus is not 2 (deviceStateInService).",
            "labels": {"domain": "hardware"},
            "per_device": True,
        },
        {
            "uid": "na-power-supply-failed-or-degraded",
            "title": "Alloy: Power supply failed or degraded",
            "expr": (
                f"(snmp_tmnxPhysChassisPMOutputStatus{{{JOB}}} == 4) or "
                f"(snmp_tmnxPhysChassisPMOutputStatus{{{JOB}}} == 5) or "
                f"(snmp_tmnxPhysChassisPMOutputStatus{{{JOB}}} == 6)"
            ),
            "for": "2m",
            "severity": "critical",
            "summary": "PSU issue on {{ $labels.device_name }}",
            "description": "Power supply output status is failed (4), out of service (5), or degraded (6).",
            "labels": {"domain": "hardware"},
            "per_device": True,
        },
        {
            "uid": "na-hardware-fru-not-in-service",
            "title": "Alloy: Hardware FRU not in service",
            "expr": (
                f"(snmp_tmnxHwOperState{{{JOB}}} == 3) or "
                f"(snmp_tmnxHwOperState{{{JOB}}} == 4) or "
                f"(snmp_tmnxHwOperState{{{JOB}}} == 5) or "
                f"(snmp_tmnxHwOperState{{{JOB}}} == 14)"
            ),
            "for": "5m",
            "severity": "critical",
            "summary": "FRU {{ $labels.hw_name }} on {{ $labels.device_name }} is not in service",
            "description": "tmnxHwOperState is outOfService (3), diagnosing (4), failed (5), or resetPending (14).",
            "labels": {"domain": "hardware"},
            "per_device": True,
        },
        {
            "uid": "na-high-chassis-temperature",
            "title": "Alloy: High chassis temperature",
            "expr": (
                f"max by(device_name) ("
                f"snmp_Temperature{{{JOB}}} or snmp_tmnxHwTemperature{{{JOB}}}"
                f") > 75"
            ),
            "for": "10m",
            "severity": "warning",
            "summary": "High temperature on {{ $labels.device_name }}",
            "description": "Max chassis/sensor temperature exceeds 75°C for 10 minutes.",
            "labels": {"domain": "hardware"},
            "per_device": True,
        },
        {
            "uid": "na-snmp-collector-heartbeat-missing",
            "title": "Alloy: SNMP collector heartbeat missing",
            "expr": (
                f'(count(count by(device_name) (snmp_CPU{{{JOB}}})) or on() vector(0)) < 1'
            ),
            "for": "5m",
            "severity": "critical",
            "summary": "No Alloy SNMP device heartbeats (snmp_CPU) detected",
            "description": "Fleet has zero snmp_CPU series for job=alloy-snmp for 5 minutes.",
            "labels": {"domain": "collection"},
            "noDataState": "OK",
        },
        {
            "uid": "na-elevated-snmp-trap-rate",
            "title": "Alloy: Elevated SNMP trap rate",
            "expr": (
                'sum(count_over_time({service_name="alloy-snmptrap"}[5m])) / 300 > 0.5'
            ),
            "datasource": "loki",
            "for": "5m",
            "severity": "info",
            "summary": "Elevated SNMP trap rate on Alloy loki.source.snmptrap",
            "description": "Trap log rate exceeds 0.5/s for 5 minutes ({service_name=alloy-snmptrap}).",
            "labels": {"domain": "events"},
        },
        {
            "uid": "na-netflow-heartbeat-missing",
            "title": "Alloy: NetFlow heartbeat missing",
            "expr": (
                '(count(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}) '
                "or on() vector(0)) < 1"
            ),
            "for": "5m",
            "severity": "warning",
            "summary": "No Alloy-native NetFlow series detected",
            "description": "Fleet has zero alloy_network_io_by_flow_bytes{integration=alloy-netflow} for 5 minutes.",
            "labels": {"domain": "collection"},
            "noDataState": "OK",
        },
    ]
    rules: list[dict[str, Any]] = []
    for spec in specs:
        rules.append(
            build_rule(
                spec,
                grafana_url=grafana_url,
                source="alloy",
                dash_uid=DASH_UID_ALLOY,
                detail_uid=DETAIL_UID_ALLOY,
            )
        )
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


def export_rules(path: Path, *, grafana_url: str = "", alloy: bool = False) -> None:
    payload = {
        "folderUID": FOLDER_UID,
        "ruleGroup": RULE_GROUP_ALLOY if alloy else RULE_GROUP,
        "interval": "1m",
        "rules": (
            alloy_rule_definitions(grafana_url)
            if alloy
            else rule_definitions(grafana_url)
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def provision(
    env: dict[str, str],
    *,
    dry_run: bool = False,
    alloy: bool = False,
) -> None:
    grafana_url = env["GRAFANA_URL"]
    group = RULE_GROUP_ALLOY if alloy else RULE_GROUP
    rules = alloy_rule_definitions(grafana_url) if alloy else rule_definitions(grafana_url)
    export_rules(
        RULES_JSON_ALLOY if alloy else RULES_JSON,
        grafana_url=grafana_url,
        alloy=alloy,
    )
    body = {
        "title": group,
        "interval": 60,
        "rules": rules,
    }
    path = f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{urllib.parse.quote(group, safe='')}"
    if dry_run:
        print(f"dry-run: would PUT {path} with {len(rules)} rules")
        for rule in rules:
            print(f"  - {rule['uid']}: {rule['title']} [{rule['labels']['severity']}]")
        print(f"Wrote {RULES_JSON_ALLOY if alloy else RULES_JSON}")
        return

    status, out = http_json(env, "PUT", path, body)
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT rule group -> {status}: {out}")
    print(f"Provisioned {len(rules)} rules in folder {FOLDER_UID} / {group}")
    for rule in rules:
        print(f"  - {rule['uid']}: {rule['title']}")


def delete_rules(env: dict[str, str], *, alloy: bool = False) -> None:
    group = RULE_GROUP_ALLOY if alloy else RULE_GROUP
    path = f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{urllib.parse.quote(group, safe='')}"
    status, out = http_json(env, "DELETE", path)
    if status not in (200, 202, 204, 404):
        raise RuntimeError(f"DELETE rule group -> {status}: {out}")
    print(f"Deleted rule group {group} (status {status})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--alloy", action="store_true", help="Provision the Alloy parallel group")
    ap.add_argument("--all", action="store_true", help="Provision ktranslate and Alloy groups")
    ap.add_argument("--delete", action="store_true", help="Remove the selected rule group")
    ap.add_argument("--export-only", action="store_true", help="Write fixtures JSON only")
    args = ap.parse_args()

    do_kt = args.all or not args.alloy
    do_alloy = args.alloy or args.all
    if args.alloy and not args.all:
        do_kt = False

    if args.export_only:
        if do_kt:
            export_rules(RULES_JSON)
            print(f"Wrote {RULES_JSON}")
        if do_alloy:
            export_rules(RULES_JSON_ALLOY, alloy=True)
            print(f"Wrote {RULES_JSON_ALLOY}")
        return 0

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    if args.delete:
        if args.dry_run:
            if do_kt:
                print(f"dry-run: would DELETE {RULE_GROUP}")
            if do_alloy:
                print(f"dry-run: would DELETE {RULE_GROUP_ALLOY}")
            return 0
        if do_kt:
            delete_rules(env, alloy=False)
        if do_alloy:
            delete_rules(env, alloy=True)
        return 0

    if do_kt:
        provision(env, dry_run=args.dry_run, alloy=False)
    if do_alloy:
        provision(env, dry_run=args.dry_run, alloy=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
