#!/usr/bin/env python3
"""Patch KTranslate Health dashboard (v2 TabsLayout) for OTLP multicontainer CHF.

Retargets NR-era labels (svc/host/provider) to OTLP ``service_name``, fixes flow
CHF metric names, adds flow/syslog spotlight panels, and updates the template variable.

Playbook: docs/grafana-dashboard-playbook.md

Usage:
  python3 local/scripts/patch-ktranslate-health-dashboard.py
  python3 local/scripts/patch-ktranslate-health-dashboard.py --dry-run
  python3 local/scripts/patch-ktranslate-health-dashboard.py --context marcnetterfield1

Dashboard UID: ktranslate-health (01. Ktranslate Health)
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "ktranslate-health-otlp-patched.json"
UID = "ktranslate-health"
NS = "stacks-1061129"

NR_DOCS = (
    "https://docs.newrelic.com/docs/network-performance-monitoring/"
    "advanced/ktranslate-container-health/"
)
KTRANSLATE_REPO = "https://github.com/kentik/ktranslate"
LOKI_SVC = '{service_name=~"ktranslate.*"}'
FLOW_SVC = 'service_name=~"ktranslate-flow.*|ktranslate-sflow.*"'
FLOW_ROLLUP = 'network_io_by_flow_bytes{integration="ktranslate-netflow"}'
PROM_DS = {"name": "grafanacloud-prom"}


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


def http_api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    token = env["GRAFANA_TOKEN"]
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def get_dashboard(env: dict[str, str]) -> dict:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{UID}"
    status, data = http_api(env, "GET", path)
    if status != 200:
        raise RuntimeError(f"GET {UID} -> {status}: {data}")
    return data


def put_dashboard(env: dict[str, str], dash: dict) -> None:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{UID}"
    status, existing = http_api(env, "GET", path)
    if status == 200 and isinstance(existing, dict):
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            dash["metadata"]["resourceVersion"] = rv
    status, out = http_api(env, "PUT", path, dash)
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT {UID} -> {status}: {out}")


def parse_gcx_json(raw: str) -> dict:
    marker = '{\n  "apiVersion"'
    start = raw.find(marker)
    if start < 0:
        start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"gcx returned no JSON: {raw[:500]}")
    obj, _ = json.JSONDecoder().raw_decode(raw, start)
    return obj


def gcx_get(context: str) -> dict:
    raw = subprocess.check_output(
        ["gcx", "--context", context, "--agent", "dashboards", "get", UID, "-o", "json"],
        stderr=subprocess.STDOUT,
    ).decode("utf-8", errors="replace")
    return parse_gcx_json(raw)


def patch_expr(expr: str) -> str:
    if not isinstance(expr, str) or not expr:
        return expr
    s = expr
    s = s.replace('{provider="kentik-agent"}', "")
    s = s.replace("{provider='kentik-agent'}", "")
    s = re.sub(r"\bkentik_ktranslate_chf_kkc_netflow\b(?!_flows)", "kentik_ktranslate_chf_kkc_netflow_flows", s)
    s = s.replace("by (svc, host, ver)", "by (service_name, ver)")
    s = s.replace("by (svc, host)", "by (service_name)")
    s = s.replace("by(host, svc, ver)", "by(service_name, ver)")
    s = s.replace("by(host,svc,ver)", "by(service_name,ver)")
    s = s.replace("by(host, svc)", "by(service_name)")
    s = s.replace("by(host,svc)", "by(service_name)")
    s = s.replace("by(host,svc,device_name)", "by(service_name,device_name)")
    s = re.sub(
        r'SELECT host AS docker_host,\s*svc AS container_service',
        "SELECT service_name AS container_service",
        s,
        flags=re.I,
    )
    s = re.sub(r"GROUP BY host,\s*svc", "GROUP BY service_name", s, flags=re.I)
    s = re.sub(
        r"JOIN B ON A\.host\s*=\s*B\.host AND A\.svc\s*=\s*B\.svc",
        "JOIN B ON A.service_name = B.service_name",
        s,
        flags=re.I,
    )
    s = re.sub(
        r"JOIN B ON A\.host=B\.host AND A\.svc=B\.svc",
        "JOIN B ON A.service_name=B.service_name",
        s,
        flags=re.I,
    )
    s = re.sub(
        r"JOIN C ON A\.host\s*=\s*C\.host AND A\.svc\s*=\s*C\.svc",
        "JOIN C ON A.service_name = C.service_name",
        s,
        flags=re.I,
    )
    s = s.replace("A.host AS docker_host, A.svc AS container_service", "A.service_name AS container_service")
    s = s.replace("{{svc}} @ {{host}}", "{{service_name}}")
    s = s.replace("{{svc}} {{ver}}", "{{service_name}} {{ver}}")
    s = s.replace("{{device_name}} ({{svc}})", "{{device_name}} ({{service_name}})")
    s = s.replace("{{svc}} / {{device_name}}", "{{service_name}}")
    s = s.replace('{service_name="ktranslate"}', LOKI_SVC)
    s = s.replace('service_name="ktranslate"', 'service_name=~"ktranslate.*"')
    s = s.replace('host_name=~"$container"', 'service_name=~"$service_name"')
    s = s.replace("| host_name=~\"$container\"", '| service_name=~"$service_name"')
    s = s.replace('sum by(host_name)', "sum by(service_name)")
    s = s.replace("$container", "$service_name")
    return s


def walk_patch(obj: Any) -> Any:
    if isinstance(obj, str):
        if obj.startswith("SELECT ") or "expr" in obj or "{" in obj or "kentik_" in obj:
            return patch_expr(obj)
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("expr", "expression", "content", "query", "stream") and isinstance(v, str):
                out[k] = patch_expr(v)
            else:
                out[k] = walk_patch(v)
        return out
    if isinstance(obj, list):
        return [walk_patch(v) for v in obj]
    return obj


def prom_query(expr: str, legend: str = "{{service_name}}", instant: bool = False) -> dict:
    return {
        "kind": "PanelQuery",
        "spec": {
            "hidden": False,
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": PROM_DS,
                "spec": {
                    "expr": expr,
                    "instant": instant,
                    "legendFormat": legend,
                    "queryType": "instant" if instant else "range",
                    "range": not instant,
                },
            },
            "refId": "A",
        },
    }


def clone_timeseries(
    template: dict,
    panel_id: int,
    title: str,
    description: str,
    queries: list[dict],
) -> dict:
    p = copy.deepcopy(template)
    spec = p["spec"]
    spec["id"] = panel_id
    spec["title"] = title
    spec["description"] = description
    for i, q in enumerate(queries):
        q["spec"]["refId"] = chr(ord("A") + i)
    spec["data"]["spec"]["queries"] = queries
    return p


def clone_stat(template: dict, panel_id: int, title: str, description: str, expr: str) -> dict:
    p = copy.deepcopy(template)
    spec = p["spec"]
    spec["id"] = panel_id
    spec["title"] = title
    spec["description"] = description
    q = spec["data"]["spec"]["queries"][0]
    if q["spec"]["query"]["group"] == "loki":
        q["spec"]["query"]["group"] = "prometheus"
        q["spec"]["query"]["datasource"] = PROM_DS
        q["spec"]["query"]["spec"] = {
            "expr": expr,
            "instant": True,
            "queryType": "instant",
            "range": False,
        }
    else:
        q["spec"]["query"]["spec"]["expr"] = expr
    return p


def make_prom_panel_query(expr: str, legend: str, ref: str = "A", hidden: bool = False) -> dict:
    return {
        "kind": "PanelQuery",
        "spec": {
            "hidden": hidden,
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": PROM_DS,
                "spec": {
                    "expr": expr,
                    "instant": False,
                    "legendFormat": legend,
                    "queryType": "range",
                    "range": True,
                },
            },
            "refId": ref,
        },
    }


def set_table_prom_queries(panel: dict, queries: list[tuple[str, str, bool]], sql: str) -> None:
    """Replace hidden prom queries + visible SQL on summary table panels."""
    qspec = panel["spec"]["data"]["spec"]["queries"]
    new_q: list[dict] = []
    for ref, expr, hidden in queries:
        new_q.append(
            {
                "kind": "PanelQuery",
                "spec": {
                    "query": {
                        "kind": "DataQuery",
                        "group": "prometheus",
                        "version": "v0",
                        "datasource": PROM_DS,
                        "spec": {
                            "expr": expr,
                            "format": "table",
                            "instant": True,
                            "legendFormat": "{{service_name}}",
                            "range": False,
                        },
                    },
                    "refId": ref,
                    "hidden": hidden,
                },
            }
        )
    new_q.append(
        {
            "kind": "PanelQuery",
            "spec": {
                "query": {
                    "kind": "DataQuery",
                    "group": "__expr__",
                    "version": "v0",
                    "spec": {"expression": sql, "type": "sql"},
                },
                "refId": chr(ord("A") + len(queries)),
                "hidden": False,
            },
        }
    )
    panel["spec"]["data"]["spec"]["queries"] = new_q


def patch_variable(dash: dict) -> None:
    dash["spec"]["variables"] = [
        {
            "kind": "QueryVariable",
            "spec": {
                "name": "service_name",
                "current": {"text": "All", "value": "$__all"},
                "label": "Collector (service_name)",
                "hide": "dontHide",
                "refresh": "onDashboardLoad",
                "skipUrlSync": False,
                "query": {
                    "kind": "DataQuery",
                    "group": "prometheus",
                    "version": "v0",
                    "datasource": PROM_DS,
                    "spec": {
                        "query": (
                            "label_values("
                            "kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total, "
                            "service_name)"
                        ),
                        "refId": "service_name-Variable-Query",
                    },
                },
                "regex": "",
                "regexApplyTo": "value",
                "sort": "alphabeticalAsc",
                "options": [],
                "multi": True,
                "includeAll": True,
                "allValue": ".*",
                "allowCustomValue": True,
            },
        }
    ]


def add_layout_item(row_items: list, name: str, x: int, y: int, w: int, h: int) -> None:
    if any(it.get("spec", {}).get("element", {}).get("name") == name for it in row_items):
        return
    row_items.append(
        {
            "kind": "GridLayoutItem",
            "spec": {
                "element": {"kind": "ElementReference", "name": name},
                "height": h,
                "width": w,
                "x": x,
                "y": y,
            },
        }
    )


def patch_dashboard(dash: dict) -> dict:
    out = copy.deepcopy(dash)
    out = walk_patch(out)
    elements = out["spec"]["elements"]
    tmpl_ts = elements["panel-35"]
    tmpl_stat = elements["panel-1"]

    # --- snmp_fail semantics ---
    p43 = elements["panel-43"]
    p43["spec"]["description"] = (
        "Devices with snmp_fail > 1 (failure codes 3–9) in the last 6h. "
        "Value 1 means healthy; see ktranslate SNMP_GOOD/SNMP_BAD_* constants."
    )
    set_table_prom_queries(
        p43,
        [
            (
                "A",
                'max by(service_name,device_name)(last_over_time(kentik_ktranslate_chf_kkc_snmp_fail[6h]))',
                True,
            )
        ],
        "SELECT service_name AS container_service, device_name AS snmp_device, "
        "__value__ AS snmp_fail FROM A WHERE __value__ > 1 LIMIT 100",
    )

    elements["panel-30"]["spec"]["title"] = "SNMP Poll Health by Device (snmp_fail)"
    elements["panel-30"]["spec"]["description"] = (
        "SNMP poll health gauge per device (kentik_ktranslate_chf_kkc_snmp_fail). "
        "**1 = healthy**; values > 1 indicate failure modes. Requires --metrics=jchf."
    )

    # --- panel-40: version / last-seen without metadata metric ---
    p40 = elements["panel-40"]
    p40["spec"]["title"] = "KTranslate Containers (CHF heartbeat)"
    p40["spec"]["description"] = (
        "Per-container build version and last CHF heartbeat via "
        "baseserver_healthcheck_execution_total (OTLP service_name label)."
    )
    set_table_prom_queries(
        p40,
        [
            (
                "A",
                "max by(service_name, ver) (last_over_time("
                "kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total[6h]))",
                True,
            ),
            (
                "B",
                "max by(service_name) (last_over_time(timestamp("
                "kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total)[6h:1m]))",
                True,
            ),
        ],
        "SELECT A.service_name AS container_service, A.ver AS ver, "
        "B.__value__*1000 AS last_seen FROM A JOIN B ON A.service_name=B.service_name LIMIT 100",
    )

    # --- panel-41 health summary ---
    set_table_prom_queries(
        elements["panel-41"],
        [
            (
                "A",
                "sum by(service_name) (last_over_time("
                "kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total[6h]))",
                True,
            ),
            ("B", "sum by(service_name) (last_over_time(kentik_ktranslate_chf_kkc_inputq[6h]))", True),
            ("C", "max by(service_name) (last_over_time(kentik_ktranslate_chf_kkc_jchfq[6h]))", True),
        ],
        "SELECT A.service_name AS container_service, A.__value__ AS healthcheck_total, "
        "B.__value__ AS input_per_second, C.__value__ AS buffer "
        "FROM A JOIN B ON A.service_name = B.service_name "
        "JOIN C ON A.service_name = C.service_name LIMIT 100",
    )

    # --- panel-42 SNMP polling summary ---
    set_table_prom_queries(
        elements["panel-42"],
        [
            ("A", "sum by(service_name) (last_over_time(kentik_ktranslate_chf_kkc_device_metrics[6h]))", True),
            ("B", "sum by(service_name) (last_over_time(kentik_ktranslate_chf_kkc_interface_metrics[6h]))", True),
        ],
        "SELECT A.service_name AS container_service, A.__value__ AS device_polls_per_second, "
        "B.__value__ AS interface_polls_per_second "
        "FROM A JOIN B ON A.service_name = B.service_name LIMIT 100",
    )

    # --- panel-44 syslog summary ---
    set_table_prom_queries(
        elements["panel-44"],
        [
            ("A", "max by(service_name)(last_over_time(kentik_ktranslate_chf_kkc_syslog_queue[6h]))", True),
            ("B", "max by(service_name)(last_over_time(kentik_ktranslate_chf_kkc_syslog_errors[6h]))", True),
            ("C", "max by(service_name)(last_over_time(kentik_ktranslate_chf_kkc_syslog_messages[6h]))", True),
        ],
        "SELECT A.service_name AS container_service, A.__value__ AS syslog_queue_total, "
        "B.__value__ AS syslog_errors_per_second, C.__value__ AS syslog_messages_per_second "
        "FROM A JOIN B ON A.service_name=B.service_name "
        "JOIN C ON A.service_name=C.service_name LIMIT 100",
    )

    # --- panel-49 flow health ---
    flow_svc = FLOW_SVC
    elements["panel-49"] = clone_timeseries(
        tmpl_ts,
        49,
        "Flow Health (CHF netflow_flows + Mimir rollup)",
        (
            "CHF **netflow_flows** ingest per flow/sFlow container (`--metrics=jchf`). "
            "Compared with rolled-up `network_io_by_flow_bytes{integration=\"ktranslate-netflow\"}` "
            "(Alloy tags rollups only; CHF keeps `ktranslate-flow-*` / `ktranslate-sflow-*`)."
        ),
        [
            make_prom_panel_query(
                f"sum by (service_name) (kentik_ktranslate_chf_kkc_netflow_flows{{{flow_svc}}})",
                "{{service_name}} CHF",
            ),
            make_prom_panel_query(
                f"sum({FLOW_ROLLUP}) * 8 / 60",
                "rollup bps (Mimir)",
                ref="B",
            ),
        ],
    )

    # --- panel-51 active containers ---
    elements["panel-51"] = clone_timeseries(
        tmpl_ts,
        51,
        "Active ktranslate Containers (CHF heartbeat)",
        "One series per container role (SNMP, flow, sFlow, syslog). Expect one line per running ktranslate process.",
        [
            make_prom_panel_query(
                "count by (service_name) ("
                "kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total)",
                "{{service_name}}",
            )
        ],
    )

    # --- panel-50 snmp_missing_meta (idempotent) ---
    if "panel-50" not in elements:
        elements["panel-50"] = clone_timeseries(
            tmpl_ts,
            50,
            "SNMP Missing Metadata by Device",
            "Devices where SNMP metadata collection failed (profile/OID gaps).",
            [make_prom_panel_query("kentik_ktranslate_chf_kkc_snmp_missing_meta", "{{device_name}}")],
        )

    # --- New role stat tiles (overview) ---
    elements["panel-52"] = clone_stat(
        tmpl_stat,
        52,
        "Flow CHF (flows/s)",
        "Sum of kentik_ktranslate_chf_kkc_netflow_flows across flow/sFlow containers.",
        f"sum(kentik_ktranslate_chf_kkc_netflow_flows{{{flow_svc}}})",
    )
    elements["panel-53"] = clone_stat(
        tmpl_stat,
        53,
        "Syslog CHF (msgs/s)",
        "Syslog messages/sec on ktranslate_syslog containers.",
        'sum(kentik_ktranslate_chf_kkc_syslog_messages{service_name=~"ktranslate-syslog.*"})',
    )
    elements["panel-54"] = clone_stat(
        tmpl_stat,
        54,
        "SNMP poll throughput",
        "SNMP device_metrics poll rate on ktranslate-snmp containers.",
        'sum(kentik_ktranslate_chf_kkc_device_metrics{service_name=~"ktranslate-snmp.*"})',
    )
    elements["panel-55"] = clone_stat(
        tmpl_stat,
        55,
        "CHF containers up",
        "Containers reporting baseserver healthcheck CHF.",
        "count(count by (service_name) (kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total))",
    )

    # --- panel-56 syslog pipeline correlation ---
    elements["panel-56"] = clone_timeseries(
        tmpl_ts,
        56,
        "Syslog Pipeline (CHF ingest vs OTLP delivery)",
        (
            "syslog_messages = listener ingest; delivery_logs_otel = logs/sec handed to Alloy. "
            "Flat delivery with rising messages ⇒ downstream OTLP/Loki issue."
        ),
        [
            make_prom_panel_query(
                'sum by (service_name) (kentik_ktranslate_chf_kkc_syslog_messages{service_name=~"ktranslate-syslog.*"})',
                "{{service_name}} messages",
            ),
            make_prom_panel_query(
                'sum by (service_name) (kentik_ktranslate_chf_kkc_delivery_logs_otel{service_name=~"ktranslate-syslog.*"})',
                "{{service_name}} delivery",
                ref="B",
            ),
        ],
    )

    # --- panel-57 flow queue pressure ---
    elements["panel-57"] = clone_timeseries(
        tmpl_ts,
        57,
        "Flow/sFlow Queue Pressure (CHF)",
        "inputq_len backlog and jchfq buffer headroom for flow containers only (~8000 = saturated).",
        [
            make_prom_panel_query(
                f"max by (service_name) (kentik_ktranslate_chf_kkc_inputq_len{{{flow_svc}}})",
                "{{service_name}} inputq_len",
            ),
            make_prom_panel_query(
                f"max by (service_name) (kentik_ktranslate_chf_kkc_jchfq{{{flow_svc}}})",
                "{{service_name}} jchfq",
                ref="B",
            ),
        ],
    )

    queue_md = (
        f"### Processing Queues — OTLP label: `service_name`\n\n"
        f"Maps [New Relic ktranslate health metrics]({NR_DOCS}) to **OTLP/Prometheus** "
        f"(`kentik_ktranslate_chf_kkc_*`) with `--metrics=jchf --sinks=otel`:\n\n"
        "| NR / ktranslate CHF | Grafana (OTLP) | What to watch |\n"
        "|---|---|---|\n"
        "| `baseserver_healthcheck_execution_total` | `..._baseserver_healthcheck_execution_total` | Must be > 0 |\n"
        "| `inputq` / `inputq_len` | `..._inputq` / `..._inputq_len` | Arrival rate; backlog ≈ 0 |\n"
        "| `jchfq` | `..._jchfq` | Buffer headroom (~8000 max) |\n"
        "| `device_metrics` | `..._device_metrics` | SNMP pollers only |\n"
        "| `netflow.flows` | `..._netflow_flows` | Flow/sFlow containers |\n"
        "| `syslog_*` | `..._syslog_queue/messages/errors` | Syslog container |\n"
        "| `delivery_logs_otel` | `..._delivery_logs_otel` | Logs/sec to Alloy |\n\n"
        "**Facet by `service_name`:** `ktranslate-snmp-*`, `ktranslate-syslog-*`, "
        "`ktranslate-flow-*`, `ktranslate-sflow-*`. Flow rollups use datapoint label "
        "`integration=ktranslate-netflow` (not `service_name`).\n\n"
        "**Logs:** `--tee_logs=true` → Loki with the same `service_name` labels."
    )
    elements["panel-20"]["spec"]["vizConfig"]["spec"]["options"]["content"] = queue_md

    elements["panel-47"]["spec"]["vizConfig"]["spec"]["options"]["content"] = (
        "## Metrics Pipeline — what data is landing in Prometheus?\n\n"
        "SNMP (`device_metrics`), syslog (`syslog_messages`), and flow (`netflow_flows` CHF + "
        f"`{FLOW_ROLLUP}` rollup). Use the **role stat row** on Overview and the "
        "flow/syslog panels below. Empty CHF with healthy SNMP usually means `--metrics=jchf` "
        "missing on that container or OTLP delivery gap — check **Queues & Delivery**."
    )

    elements["panel-45"]["spec"]["vizConfig"]["spec"]["options"]["content"] = (
        f"## Overview — is KTranslate running and healthy?\n\n"
        f"| Role | `service_name` pattern | CHF signals |\n"
        f"|---|---|---|\n"
        f"| SNMP + traps | `ktranslate-snmp-*` | device/interface_metrics, snmp_fail, snmp_traps |\n"
        f"| NetFlow | `ktranslate-flow-*` | netflow_flows, inputq |\n"
        f"| sFlow | `ktranslate-sflow-*` | netflow_flows, jchfq |\n"
        f"| Syslog | `ktranslate-syslog-*` | syslog_messages, syslog_queue, delivery_logs_otel |\n\n"
        f"Filter all panels with the **Collector (service_name)** dropdown. "
        f"Requires `--metrics=jchf` on every ktranslate container ([ktranslate]({KTRANSLATE_REPO}))."
    )

    intro = elements.get("panel-3", elements.get("panel-45"))
    if intro:
        intro["spec"]["vizConfig"]["spec"]["options"]["content"] = (
            "## KTranslate Health Dashboard\n\n"
            "Monitors **ktranslate** collector containers (SNMP, flow, sFlow, syslog) via CHF "
            "metrics (`kentik_ktranslate_chf_kkc_*`). Use the **Collector (service_name)** dropdown "
            "to filter panels.\n\n"
            "**Reading the stats above:** upload error counters should be zero. "
            "Role stat row confirms flow/syslog CHF is live after the OTLP jchf fix."
        )

    patch_variable(out)

    # --- Layout (idempotent adds) ---
    tabs = out["spec"]["layout"]["spec"]["tabs"]

    ov_row = tabs[0]["spec"]["layout"]["spec"]["rows"][1]["spec"]["layout"]["spec"]["items"]
    add_layout_item(ov_row, "panel-52", 0, 29, 6, 4)
    add_layout_item(ov_row, "panel-53", 6, 29, 6, 4)
    add_layout_item(ov_row, "panel-54", 12, 29, 6, 4)
    add_layout_item(ov_row, "panel-55", 18, 29, 6, 4)

    dev_row = tabs[1]["spec"]["layout"]["spec"]["rows"][1]["spec"]["layout"]["spec"]["items"]
    add_layout_item(dev_row, "panel-50", 0, 36, 24, 8)

    met_row = tabs[2]["spec"]["layout"]["spec"]["rows"][1]["spec"]["layout"]["spec"]["items"]
    for item in met_row:
        if item["spec"]["element"]["name"] == "panel-49":
            item["spec"]["height"] = 8
    add_layout_item(met_row, "panel-56", 0, 41, 24, 8)
    add_layout_item(met_row, "panel-57", 0, 49, 24, 8)

    out["spec"]["elements"] = elements
    out["spec"]["description"] = (
        "ktranslate collector health (--metrics=jchf): SNMP, flow, sFlow, traps, syslog. "
        "OTLP labels (service_name). Aligned with NR container health guide."
    )
    ann = out.setdefault("metadata", {}).setdefault("annotations", {})
    ann["grafana.app/message"] = (
        "OTLP CHF relabel: service_name per container; flow rollups use integration label"
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context", help="gcx context (optional; default HTTP via local/.env)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env()
    use_gcx = bool(args.context)

    if use_gcx:
        dash = gcx_get(args.context)
    else:
        if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
            raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env (or pass --context)")
        dash = get_dashboard(env)

    layout_kind = dash.get("spec", {}).get("layout", {}).get("kind")
    gen = dash.get("metadata", {}).get("generation", "?")
    print(f"Fetched {UID} layout={layout_kind} generation={gen}")
    if layout_kind != "TabsLayout":
        print("ERROR: expected TabsLayout — aborting")
        return 1

    patched = patch_dashboard(dash)
    OUT.write_text(json.dumps(patched, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")

    if args.dry_run:
        print("dry-run: not pushing to Grafana")
        return 0

    if use_gcx:
        out = Path(tempfile.gettempdir()) / "ktranslate-health-patched.json"
        out.write_text(json.dumps(patched, indent=2), encoding="utf-8")
        subprocess.run(
            ["gcx", "--context", args.context, "--agent", "dashboards", "update", UID, "-f", str(out)],
            check=True,
        )
    else:
        put_dashboard(env, patched)

    base = (env.get("GRAFANA_URL") or "https://marcnetterfield1.grafana.net").rstrip("/")
    print(f"Patched {base}/d/{UID}")
    kind = patched.get("spec", {}).get("layout", {}).get("kind")
    print(f"post-patch layout={kind} elements={len(patched.get('spec', {}).get('elements') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
