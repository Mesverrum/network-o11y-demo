#!/usr/bin/env python3
"""First-batch NetworkDevice measurements + Knowledge Graph insights.

Recording rules stamp asserts_env/site + device_name (measurements).
Grafana-managed alerts add asserts_entity_type / category / severity so RCA
workbench can attach Insights to NetworkDevice — not topology info gauges.

Usage:
  python3 local/scripts/provision-network-device-insights.py --dry-run
  python3 local/scripts/provision-network-device-insights.py
  python3 local/scripts/provision-network-device-insights.py --verify
  python3 local/scripts/provision-network-device-insights.py --delete
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
YAML_OUT = ROOT / "fixtures" / "conversation-kg" / "device-insights.yaml"
FOLDER_UID = "network-lab"
REC_GROUP = "Network Lab / device insights"
ALERT_GROUP = "Network Lab / device insights alerts"
INTERVAL_SEC = 60
PROM_DS = "grafanacloud-prom"
DETAIL_UID = "alloy-device-details"
ASSERTS_ENV = "network-lab"
ASSERTS_SITE = "colocated"
ACCESS_IF = "ethernet-1/1"


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


def _scope(inner: str) -> str:
    """Stamp KG scope labels onto each series (Grafana recording labels are extra)."""
    return (
        "label_replace(label_replace(\n"
        f"{inner}\n"
        f', "asserts_env", "{ASSERTS_ENV}", "", "")\n'
        f', "asserts_site", "{ASSERTS_SITE}", "", "")'
    )


def _cpu() -> str:
    return _scope("max by (device_name) (snmp_CPU)")


def _memory() -> str:
    return _scope("max by (device_name) (device:snmp_MemoryUtilization:percent)")


def _snmp_unhealthy() -> str:
    # Clos NetworkDevices only (snmp_CPU). Campus dist-* can be down
    # without being KG entities — do not attach Insights to those.
    # Alloy scrape health is up{job="alloy-snmp"} (1=ok), not PollingHealth.
    return _scope(
        """(
  count by (device_name) (
    max by (device_name) (up{job="alloy-snmp",snmp_tier="hot"}) == 0
    and on (device_name) snmp_CPU
  )
)
or
(
  count by (device_name) (snmp_CPU) * 0
)"""
    )


def _access_if_down() -> str:
    # Workshop fault: leaf1 ethernet-1/1. IF-MIB 1=up, 2=down.
    return _scope(
        f"""(
  count by (device_name) (
    (
      max by (device_name) (snmp_ifAdminStatus{{if_interface_name="{ACCESS_IF}"}}) == 1
    )
    and
    (
      max by (device_name) (snmp_ifOperStatus{{if_interface_name="{ACCESS_IF}"}}) == 2
    )
    and on (device_name) snmp_CPU
  )
)
or
(
  count by (device_name) (snmp_CPU) * 0
)"""
    )


def _interface_down() -> str:
    # Per Interface entity (device:ifName). Zero-fill role-bearing ports so
    # only those names fire; fault-only ports appear when they join interface_info.
    return _scope(
        """label_join(
  (
    count by (device_name, if_interface_name) (
      (
        max by (device_name, if_interface_name) (snmp_ifAdminStatus) == 1
      )
      and
      (
        max by (device_name, if_interface_name) (snmp_ifOperStatus) == 2
      )
      and on (device_name, if_interface_name) network_lab:interface_info
    )
  )
  or
  (
    count by (device_name, if_interface_name) (network_lab:interface_info) * 0
  ),
  "interface", ":", "device_name", "if_interface_name"
)"""
    )


def recording_specs() -> list[dict[str, str]]:
    return [
        {
            "uid": "nlabdi-cpu",
            "title": "NetworkDevice CPU percent",
            "record": "network_lab:device_cpu:percent",
            "expr": _cpu(),
        },
        {
            "uid": "nlabdi-mem",
            "title": "NetworkDevice memory percent",
            "record": "network_lab:device_memory:percent",
            "expr": _memory(),
        },
        {
            "uid": "nlabdi-snmp-unhealthy",
            "title": "NetworkDevice SNMP unhealthy",
            "record": "network_lab:device_snmp_unhealthy",
            "expr": _snmp_unhealthy(),
        },
        {
            "uid": "nlabdi-access-down",
            "title": "NetworkDevice access iface down",
            "record": "network_lab:device_access_if_down",
            "expr": _access_if_down(),
        },
        {
            "uid": "nlabdi-iface-down",
            "title": "Interface oper-down",
            "record": "network_lab:interface_down",
            "expr": _interface_down(),
        },
    ]


def alert_definitions() -> list[dict[str, Any]]:
    return [
        {
            "uid": "nlabdi-alert-snmp",
            "title": "NetworkDevice SNMP polling unhealthy",
            "expr": "network_lab:device_snmp_unhealthy > 0 and on (device_name) network_lab:device_cpu:percent",
            "for": "5m",
            "op": "gt",
            "threshold": 0,
            "severity": "critical",
            "category": "failure",
            "summary": "SNMP polling unhealthy on {{ $labels.device_name }}",
            "description": (
                "Alloy SNMP scrape up{job=\"alloy-snmp\",snmp_tier=\"hot\"} is 0 "
                "for 5 minutes. Insight category=failure on NetworkDevice."
            ),
        },
        {
            "uid": "nlabdi-alert-access",
            "title": "NetworkDevice access interface down",
            "expr": "network_lab:device_access_if_down > 0 and on (device_name) network_lab:device_cpu:percent",
            "for": "2m",
            "op": "gt",
            "threshold": 0,
            "severity": "warning",
            "category": "failure",
            "summary": (
                f"{ACCESS_IF} admin-up/oper-down on {{{{ $labels.device_name }}}}"
            ),
            "description": (
                f"Workshop path: shut {ACCESS_IF} on leaf1 and this NetworkDevice "
                "insight should fire while Endpoint–Endpoint ROUTES stay drawn."
            ),
        },
        {
            "uid": "nlabdi-alert-iface",
            "title": "Interface oper-down",
            "expr": "network_lab:interface_down > 0",
            "for": "2m",
            "op": "gt",
            "threshold": 0,
            "severity": "warning",
            "category": "failure",
            "entity_type": "Interface",
            "summary": "{{ $labels.interface }} admin-up/oper-down",
            "description": (
                "Role-bearing or currently faulted Clos port is oper-down. "
                "Insight category=failure on Interface (leaf1:ethernet-1/1 is the workshop path)."
            ),
        },
        {
            "uid": "nlabdi-alert-cpu",
            "title": "NetworkDevice high CPU",
            "expr": "network_lab:device_cpu:percent > 85",
            "for": "10m",
            "op": "gt",
            "threshold": 85,
            "severity": "warning",
            "category": "saturation",
            "summary": "CPU above 85% on {{ $labels.device_name }}",
            "description": "Device CPU (snmp_CPU) above 85% for 10 minutes.",
        },
        {
            "uid": "nlabdi-alert-mem",
            "title": "NetworkDevice high memory",
            "expr": "network_lab:device_memory:percent > 90",
            "for": "10m",
            "op": "gt",
            "threshold": 90,
            "severity": "warning",
            "category": "saturation",
            "summary": "Memory above 90% on {{ $labels.device_name }}",
            "description": "device:snmp_MemoryUtilization:percent above 90% for 10 minutes.",
        },
    ]


def recording_rule(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "uid": spec["uid"],
        "title": spec["title"],
        "for": "0s",
        "orgId": 1,
        "labels": {
            "source": "network-lab",
            "kind": "device-insights",
            "asserts_env": ASSERTS_ENV,
            "asserts_site": ASSERTS_SITE,
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


def alert_rule(defn: dict[str, Any], grafana_url: str) -> dict[str, Any]:
    runbook = (
        f"{grafana_url.rstrip('/')}/d/{DETAIL_UID}"
        "?var-instance={{ $labels.device_name }}"
    )
    return {
        "uid": defn["uid"],
        "title": defn["title"],
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 600, "to": 0},
                "datasourceUid": PROM_DS,
                "model": {
                    "datasource": {"type": "prometheus", "uid": PROM_DS},
                    "expr": defn["expr"],
                    "instant": True,
                    "intervalMs": 1000,
                    "legendFormat": "__auto",
                    "maxDataPoints": 43200,
                    "refId": "A",
                },
            },
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 0, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                    "expression": "A",
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                    "reducer": "last",
                    "refId": "B",
                    "settings": {"mode": "dropNN"},
                    "type": "reduce",
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": 0, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "conditions": [
                        {
                            "evaluator": {"params": [defn["threshold"]], "type": defn["op"]},
                            "operator": {"type": "and"},
                            "query": {"params": ["C"]},
                            "reducer": {"params": [], "type": "last"},
                            "type": "query",
                        }
                    ],
                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                    "expression": "B",
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                    "refId": "C",
                    "type": "threshold",
                },
            },
        ],
        "noDataState": "OK",
        "execErrState": "Error",
        "for": defn["for"],
        "annotations": {
            "summary": defn["summary"],
            "description": defn["description"],
            "runbook_url": runbook,
        },
        "labels": {
            "category": "network",
            "source": "network-lab",
            "kind": "device-insights",
            "severity": defn["severity"],
            "asserts_entity_type": defn.get("entity_type", "NetworkDevice"),
            "asserts_alert_category": defn["category"],
            "asserts_severity": defn["severity"],
            "asserts_env": ASSERTS_ENV,
            "asserts_site": ASSERTS_SITE,
        },
        "isPaused": False,
    }


def export_yaml() -> None:
    lines = [
        "# NetworkDevice measurements + KG insight alerts.",
        "# Source: provision-network-device-insights.py",
        "#",
        "# Insights need real series (not vector(1) catalogs) plus alert labels",
        "# asserts_entity_type / asserts_alert_category / asserts_severity and",
        "# scope labels asserts_env / asserts_site on the firing series.",
        "",
        "groups:",
        f"  - name: {REC_GROUP}",
        f"    interval: {INTERVAL_SEC // 60}m",
        "    rules:",
    ]
    for spec in recording_specs():
        lines.append(f"      - record: {spec['record']}")
        lines.append(f"        labels:")
        lines.append(f"          asserts_env: {ASSERTS_ENV}")
        lines.append(f"          asserts_site: {ASSERTS_SITE}")
        expr = spec["expr"].rstrip()
        lines.append("        expr: |")
        for eline in expr.splitlines():
            lines.append(f"          {eline}")
        lines.append("")
    lines.append(f"  - name: {ALERT_GROUP}")
    lines.append(f"    interval: {INTERVAL_SEC // 60}m")
    lines.append("    rules:")
    for defn in alert_definitions():
        lines.append(f"      - alert: {defn['uid']}")
        lines.append(f"        expr: {defn['expr']}")
        lines.append(f"        for: {defn['for']}")
        lines.append("        labels:")
        lines.append(f"          asserts_entity_type: {defn.get('entity_type', 'NetworkDevice')}")
        lines.append(f"          asserts_alert_category: {defn['category']}")
        lines.append(f"          asserts_severity: {defn['severity']}")
        lines.append(f"        annotations:")
        lines.append(f"          summary: {defn['summary']}")
        lines.append("")
    YAML_OUT.parent.mkdir(parents=True, exist_ok=True)
    YAML_OUT.write_text("\n".join(lines), encoding="utf-8")


def http_json(
    env: dict[str, str],
    method: str,
    path: str,
    body: Any | None = None,
) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    headers = {
        "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Disable-Provenance": "true",
    }
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
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


def group_path(name: str, folder: str = FOLDER_UID) -> str:
    return (
        f"/api/v1/provisioning/folder/{folder}/rule-groups/"
        f"{urllib.parse.quote(name, safe='')}"
    )


def put_group(env: dict[str, str], name: str, interval: int, rules: list[dict], folder: str) -> None:
    body = {"title": name, "interval": interval, "rules": rules}
    status, out = http_json(env, "PUT", group_path(name, folder), body)
    if status == 404:
        status, out = http_json(
            env, "POST", f"/api/v1/provisioning/folder/{folder}/rule-groups", body
        )
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT/POST {name} -> {status}: {out}")
    print(f"Provisioned {len(rules)} rules in {folder} / {name}")


def delete_group(env: dict[str, str], name: str, folder: str) -> None:
    status, out = http_json(env, "DELETE", group_path(name, folder))
    if status not in (200, 202, 204, 404):
        raise RuntimeError(f"DELETE {name} -> {status}: {out}")
    print(f"Deleted {name} (status {status})")


def promql(env: dict[str, str], expr: str) -> list:
    base = env["GRAFANA_URL"].rstrip("/")
    q = urllib.parse.urlencode({"query": expr})
    url = f"{base}/api/datasources/proxy/uid/{PROM_DS}/api/v1/query?{q}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=60) as resp:
        body = json.loads(resp.read().decode())
    if body.get("status") != "success":
        return []
    return body.get("data", {}).get("result") or []


def verify(env: dict[str, str], *, wait_sec: int = 0) -> None:
    if wait_sec:
        print(f"waiting {wait_sec}s for first evaluation...")
        time.sleep(wait_sec)
    for spec in recording_specs():
        name = spec["record"]
        rows = promql(env, f"count({name})")
        n = rows[0]["value"][1] if rows else "0"
        print(f"  {name}  series={n}")
    print("access_if_down:")
    for row in promql(
        env, "count by (device_name) (network_lab:device_access_if_down > 0)"
    ):
        print(f"  {row.get('metric', {})} = {row.get('value', [None, '?'])[1]}")
    print("cpu:")
    for row in promql(
        env, "max by (device_name) (network_lab:device_cpu:percent)"
    ):
        print(f"  {row.get('metric', {})} = {row.get('value', [None, '?'])[1]}")
    print("interface_down:")
    for row in promql(env, "network_lab:interface_down > 0"):
        print(f"  {row.get('metric', {})} = {row.get('value', [None, '?'])[1]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--folder", default=FOLDER_UID)
    args = ap.parse_args()

    export_yaml()
    recs = recording_specs()
    alerts = alert_definitions()
    if args.export_only:
        print(f"Wrote {YAML_OUT}")
        return 0

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")
    grafana_url = env["GRAFANA_URL"]

    if args.delete:
        if args.dry_run:
            print(f"dry-run: would DELETE {REC_GROUP} and {ALERT_GROUP}")
            return 0
        delete_group(env, ALERT_GROUP, args.folder)
        delete_group(env, REC_GROUP, args.folder)
        return 0

    if args.dry_run:
        print(f"dry-run: {REC_GROUP} recordings={len(recs)}")
        for spec in recs:
            print(f"  record {spec['record']}")
        print(f"dry-run: {ALERT_GROUP} alerts={len(alerts)}")
        for defn in alerts:
            print(
                f"  alert {defn['title']} "
                f"entity={defn.get('entity_type', 'NetworkDevice')} "
                f"category={defn['category']} severity={defn['severity']}"
            )
        print(f"Wrote {YAML_OUT}")
        return 0

    put_group(env, REC_GROUP, INTERVAL_SEC, [recording_rule(s) for s in recs], args.folder)
    put_group(
        env,
        ALERT_GROUP,
        INTERVAL_SEC,
        [alert_rule(d, grafana_url) for d in alerts],
        args.folder,
    )
    if args.verify:
        verify(env, wait_sec=args.wait)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
