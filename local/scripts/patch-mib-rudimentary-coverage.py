#!/usr/bin/env python3
"""Add rudimentary has_* gates + panels for MIB coverage gaps on Device Details.

Patches KtransToGrafana dashboards/04 Network Device Details.json:
  - has_tmnx_hw + Hardware Inventory table (tmnxHwOperState)
  - has_lenovo_health / has_lenovo_psu / has_lenovo_fan + one panel each
  - Fix empty has_fan_state / has_temp_sensor gate metrics

Usage:
  python3 local/scripts/patch-mib-rudimentary-coverage.py
  python3 local/scripts/patch-mib-rudimentary-coverage.py --push   # PUT to marc only (GRAFANA_URL)

Device Details MIB experiments stay on marcnetterfield1 until explicitly synced
(--include-device-details on sync-ktranslate-marc-to-dev.py).
"""
from __future__ import annotations

import argparse
import copy
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ktranslate_upstream import load_local_env, path_for_uid  # noqa: E402

UID = "ktranslate-device-details"
HARDWARE_TAB = 2  # Sensors / hardware tab with Nokia Chassis Health


def load_env() -> dict[str, str]:
    load_local_env()
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(base: str, token: str, method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:3000]}


def make_gate(name: str, metric: str) -> dict:
    # Hyphenated Prometheus names are illegal identifiers — gate via __name__.
    if "-" in metric:
        gate_metric = ""
        gate_query = (
            f'label_values({{__name__="{metric}",device_name=~"$instance"}},device_name)'
        )
    else:
        gate_metric = metric
        gate_query = f'label_values({metric}{{device_name=~"$instance"}},device_name)'
    return {
        "kind": "QueryVariable",
        "spec": {
            "name": name,
            "current": {"text": "", "value": ""},
            "hide": "hideVariable",
            "refresh": "onDashboardLoad",
            "skipUrlSync": False,
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": {"name": "grafanacloud-prom"},
                "spec": {
                    "label": "device_name",
                    "labelFilters": [
                        {"label": "device_name", "op": "=~", "value": "$instance"}
                    ],
                    "metric": gate_metric,
                    "qryType": 1,
                    "query": gate_query,
                    "refId": "PrometheusVariableQueryEditor-VariableQuery",
                },
            },
            "regex": "",
            "regexApplyTo": "value",
            "sort": "disabled",
            "options": [],
            "multi": False,
            "includeAll": False,
            "allowCustomValue": True,
        },
    }


def make_table_panel(
    pid: int,
    title: str,
    expr: str,
    description: str,
    value_field: str,
    rename: dict[str, str] | None = None,
) -> dict:
    rename = rename or {}
    index_rename = {"Index": "Index", value_field: rename.get(value_field, "Value")}
    # pull common entity tags into columns when present
    for tag, label in (
        ("hw_name", "Name"),
        ("hw_class", "Class"),
        ("hw_serial", "Serial"),
        ("psu_name", "PSU"),
        ("fan_name", "Fan"),
    ):
        index_rename[tag] = label
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": description,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": [
                        {
                            "kind": "PanelQuery",
                            "spec": {
                                "query": {
                                    "kind": "DataQuery",
                                    "group": "prometheus",
                                    "version": "v0",
                                    "datasource": {"name": "grafanacloud-prom"},
                                    "spec": {
                                        "expr": expr,
                                        "format": "table",
                                        "instant": True,
                                        "legendFormat": "",
                                        "range": False,
                                    },
                                },
                                "refId": "A",
                                "hidden": False,
                            },
                        }
                    ],
                    "transformations": [
                        {
                            "kind": "Transformation",
                            "group": "labelsToFields",
                            "spec": {"options": {}},
                        },
                        {
                            "kind": "Transformation",
                            "group": "merge",
                            "spec": {"options": {}},
                        },
                        {
                            "kind": "Transformation",
                            "group": "organize",
                            "spec": {
                                "options": {
                                    "excludeByName": {
                                        "Time": True,
                                        "Value": True,
                                        "__name__": True,
                                        "deployment_host": True,
                                        "device_name": True,
                                        "eventType": True,
                                        "instrumentation_name": True,
                                        "job": True,
                                        "mib_name": True,
                                        "mib_table": True,
                                        "objectIdentifier": True,
                                        "provider": True,
                                        "service_name": True,
                                        "src_addr": True,
                                        "snmp_group": True,
                                        "tags_container_service": True,
                                        "tags_kentik_model": True,
                                    },
                                    "renameByName": index_rename,
                                }
                            },
                        },
                    ],
                    "queryOptions": {},
                },
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": "table",
                "version": "11.0.0",
                "spec": {
                    "options": {"cellHeight": "sm", "showHeader": True},
                    "fieldConfig": {
                        "defaults": {
                            "custom": {"align": "auto", "filterable": True},
                        },
                        "overrides": [],
                    },
                },
            },
        },
    }


def make_stat_panel(pid: int, title: str, expr: str, description: str) -> dict:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": description,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": [
                        {
                            "kind": "PanelQuery",
                            "spec": {
                                "query": {
                                    "kind": "DataQuery",
                                    "group": "prometheus",
                                    "version": "v0",
                                    "datasource": {"name": "grafanacloud-prom"},
                                    "spec": {
                                        "expr": expr,
                                        "instant": True,
                                        "legendFormat": "__auto",
                                        "range": False,
                                    },
                                },
                                "refId": "A",
                                "hidden": False,
                            },
                        }
                    ],
                    "transformations": [],
                    "queryOptions": {},
                },
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": "stat",
                "version": "11.0.0",
                "spec": {
                    "options": {
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "value",
                        "graphMode": "none",
                        "textMode": "auto",
                    },
                    "fieldConfig": {"defaults": {}, "overrides": []},
                },
            },
        },
    }


def conditional_row(title: str, gate: str, items: list[dict]) -> dict:
    return {
        "kind": "RowsLayoutRow",
        "spec": {
            "title": title,
            "collapse": False,
            "hideHeader": False,
            "fillScreen": False,
            "conditionalRendering": {
                "kind": "ConditionalRenderingGroup",
                "spec": {
                    "visibility": "show",
                    "condition": "and",
                    "items": [
                        {
                            "kind": "ConditionalRenderingVariable",
                            "spec": {
                                "variable": gate,
                                "operator": "matches",
                                "value": ".+",
                            },
                        }
                    ],
                },
            },
            "layout": {"kind": "GridLayout", "spec": {"items": items}},
        },
    }


def grid_item(name: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "kind": "GridLayoutItem",
        "spec": {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "element": {"kind": "ElementReference", "name": name},
        },
    }


def upsert_variable(variables: list[dict], gate: dict) -> None:
    name = gate["spec"]["name"]
    for i, v in enumerate(variables):
        if (v.get("spec") or {}).get("name") == name:
            # preserve current; update metric fields
            variables[i] = gate
            return
    variables.append(gate)


def fix_empty_gates(variables: list[dict]) -> None:
    fixes = {
        "has_fan_state": "kentik_snmp_lenovoEnvMibFanState",
        "has_temp_sensor": "kentik_snmp_lenovoEnvMibTempSensorState",
    }
    for v in variables:
        spec = v.get("spec") or {}
        name = spec.get("name")
        if name not in fixes:
            continue
        q = ((spec.get("query") or {}).get("spec")) or {}
        if q.get("metric"):
            continue
        metric = fixes[name]
        q["metric"] = metric
        q["query"] = f'label_values({metric}{{device_name=~"$instance"}},device_name)'
        print(f"fixed empty gate {name} -> {metric}")


def max_panel_id(elements: dict) -> int:
    m = 0
    for el in elements.values():
        pid = (el.get("spec") or {}).get("id")
        if isinstance(pid, int):
            m = max(m, pid)
    return m


def patch(dash: dict) -> dict:
    dash = copy.deepcopy(dash)
    elements = dash["spec"]["elements"]
    variables = dash["spec"]["variables"]
    fix_empty_gates(variables)

    gates = [
        ("has_tmnx_hw", "kentik_snmp_tmnxHwOperState"),
        ("has_lenovo_health", "kentik_snmp_hwGlobalHealthStatus"),
        ("has_lenovo_psu", "kentik_snmp_lenovoEnvMibPowerSupplyState"),
        ("has_lenovo_fan", "kentik_snmp_lenovoEnvMibFanState"),
    ]
    for name, metric in gates:
        upsert_variable(variables, make_gate(name, metric))
        print(f"gate {name} -> {metric}")

    next_id = max_panel_id(elements) + 1
    panels = {
        "panel-tmnx-hw": make_table_panel(
            next_id,
            "Nokia Hardware Inventory",
            'kentik_snmp_tmnxHwOperState{snmp_group=~"$snmp_group",device_name=~"$instance"}',
            "TIMETRA-CHASSIS-MIB tmnxHwTable oper-state (rudimentary MIB coverage).",
            "tmnxHwOperState",
            {"tmnxHwOperState": "Oper State"},
        ),
        "panel-lenovo-health": make_stat_panel(
            next_id + 1,
            "Lenovo Global Health",
            'kentik_snmp_hwGlobalHealthStatus{snmp_group=~"$snmp_group",device_name=~"$instance"}',
            "LENOVO-TOR-MIBS hwGlobalHealthStatus (rudimentary).",
        ),
        "panel-lenovo-psu": make_table_panel(
            next_id + 2,
            "Lenovo Power Supplies",
            'kentik_snmp_lenovoEnvMibPowerSupplyState{snmp_group=~"$snmp_group",device_name=~"$instance"}',
            "LENOVO-ENV-MIB power supply table (rudimentary).",
            "lenovoEnvMibPowerSupplyState",
            {"lenovoEnvMibPowerSupplyState": "State"},
        ),
        "panel-lenovo-fan": make_table_panel(
            next_id + 3,
            "Lenovo Fans",
            'kentik_snmp_lenovoEnvMibFanState{snmp_group=~"$snmp_group",device_name=~"$instance"}',
            "LENOVO-ENV-MIB fan table (rudimentary).",
            "lenovoEnvMibFanState",
            {"lenovoEnvMibFanState": "State"},
        ),
    }
    for name, panel in panels.items():
        elements[name] = panel
        print(f"panel {name} id={panel['spec']['id']}")

    rows = dash["spec"]["layout"]["spec"]["tabs"][HARDWARE_TAB]["spec"]["layout"]["spec"]["rows"]
    # Avoid duplicate rows on re-run
    existing_titles = {(r.get("spec") or {}).get("title") for r in rows}
    new_rows = [
        (
            "Nokia Hardware Inventory",
            "has_tmnx_hw",
            [grid_item("panel-tmnx-hw", 0, 0, 24, 10)],
        ),
        (
            "Lenovo Health",
            "has_lenovo_health",
            [grid_item("panel-lenovo-health", 0, 0, 8, 5)],
        ),
        (
            "Lenovo Power Supplies",
            "has_lenovo_psu",
            [grid_item("panel-lenovo-psu", 0, 0, 24, 8)],
        ),
        (
            "Lenovo Fans",
            "has_lenovo_fan",
            [grid_item("panel-lenovo-fan", 0, 0, 24, 8)],
        ),
    ]
    for title, gate, items in new_rows:
        if title in existing_titles:
            # replace existing row
            for i, r in enumerate(rows):
                if (r.get("spec") or {}).get("title") == title:
                    rows[i] = conditional_row(title, gate, items)
                    print(f"replaced row {title}")
                    break
        else:
            rows.append(conditional_row(title, gate, items))
            print(f"added row {title}")

    return dash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true", help="PUT to GRAFANA_URL (marcnetterfield1 only)")
    args = parser.parse_args()

    path = path_for_uid(UID)
    dash = json.loads(path.read_text(encoding="utf-8"))
    patched = patch(dash)
    path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")

    if not args.push:
        return 0

    env = load_env()
    url = env["GRAFANA_URL"]
    token = env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
    status, existing = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    if status != 200:
        raise SystemExit(f"GET marc failed {status}")
    body = copy.deepcopy(patched)
    body["metadata"]["namespace"] = ns
    body["metadata"]["name"] = UID
    body["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
    for k in ("generation", "creationTimestamp", "uid", "managedFields"):
        body["metadata"].pop(k, None)
    body.pop("status", None)
    ann = body["metadata"].setdefault("annotations", {})
    ann["grafana.app/folder"] = existing.get("metadata", {}).get("annotations", {}).get(
        "grafana.app/folder", "network-lab"
    )
    status, data = api(
        url, token, "PUT", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}", body
    )
    print(f"PUT marc -> {status} gen={(data or {}).get('metadata', {}).get('generation')}")
    if status not in (200, 201):
        raise SystemExit(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
