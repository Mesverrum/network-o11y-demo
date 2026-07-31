#!/usr/bin/env python3
"""Patch ktranslate dashboards 03–04 event/trap/syslog Loki panels (v2 TabsLayout-safe).

Uses structured JSON filters (eventType, instrumentation_name) instead of substring
matching so traps, device syslog, and internal collector logs stay separated.

Workflow:
  1. python3 local/scripts/reorganize-marcnetterfield-dashboards.py pull
  2. python3 local/scripts/patch-ktranslate-event-log-panels.py [--dry-run]
  3. Verify layout.kind unchanged; spot-check Events tabs in Grafana

Usage:
  python3 local/scripts/patch-ktranslate-event-log-panels.py
  python3 local/scripts/patch-ktranslate-event-log-panels.py --dry-run
"""
from __future__ import annotations

import argparse
import copy
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / ".dash-payloads" / "marcnetterfield-live"
NS = "stacks-1061129"

LOKI_SVC = '{service_name=~"ktranslate.*"}'
SYSLOG_JSON = f'{LOKI_SVC} | json | instrumentation_name="ktranslate-syslog"'
TRAP_JSON = f'{LOKI_SVC} | json | eventType="KSnmpTrap"'
INTERNAL_TEXT = f'{LOKI_SVC} != "{{" | pattern `<_> ktranslate/<component> [<level>] <msg>`'
SYSLOG_COLLECTOR_INTERNAL = (
    f'{LOKI_SVC} != "{{" | pattern `<_> ktranslate/<component> [<level>] <msg>` | component="syslog"'
)

TARGETS = [
    "ktranslate-device-summary",
    "ktranslate-device-details",
]


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


def put_dashboard(env: dict[str, str], uid: str, dash: dict) -> None:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    status, existing = http_api(env, "GET", path)
    if status == 200 and isinstance(existing, dict):
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            dash["metadata"]["resourceVersion"] = rv
        labels = (existing.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in labels:
            dash.setdefault("metadata", {}).setdefault("labels", {})
            dash["metadata"]["labels"]["grafana.app/deprecatedInternalID"] = labels[
                "grafana.app/deprecatedInternalID"
            ]
    status, out = http_api(env, "PUT", path, dash)
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT {uid} -> {status}: {out}")


def loki_query_spec(panel: dict) -> dict | None:
    data = panel.get("spec", {}).get("data", {})
    if data.get("kind") != "QueryGroup":
        return None
    queries = data.get("spec", {}).get("queries", [])
    if not queries:
        return None
    query = queries[0].get("spec", {}).get("query", {})
    if query.get("group") != "loki":
        return None
    spec = query.get("spec", {})
    return spec if isinstance(spec, dict) else None


def set_loki_expr(panel: dict, expr: str) -> bool:
    qspec = loki_query_spec(panel)
    if not qspec:
        return False
    if qspec.get("expr") == expr:
        return False
    qspec["expr"] = expr
    return True


def clone_panel(template: dict, panel_id: int, title: str, description: str, expr: str) -> dict:
    panel = copy.deepcopy(template)
    panel["spec"]["id"] = panel_id
    panel["spec"]["title"] = title
    panel["spec"]["description"] = description
    queries = panel["spec"]["data"]["spec"]["queries"]
    queries[:] = queries[:1]
    queries[0]["spec"]["query"]["spec"]["expr"] = expr
    return panel


def patch_device_details(manifest: dict) -> list[str]:
    changes: list[str] = []
    elements = manifest.get("spec", {}).get("elements", {})
    device_syslog = f'{SYSLOG_JSON} | device_name=~"$instance"'
    device_trap = f'{TRAP_JSON} | device_name=~"$instance"'

    expr_map = {
        "panel-335": (
            "Syslog Events (range)",
            f'sum(count_over_time({device_syslog} [$__range]))',
        ),
        "panel-336": ("Recent Syslog", device_syslog),
        "panel-337": (
            "Trap Events (range)",
            f'sum(count_over_time({device_trap} [$__range]))',
        ),
        "panel-339": ("Recent SNMP Traps", device_trap),
        "panel-340": (
            "Syslog Events Over Time",
            f'sum(count_over_time({device_syslog} [$__interval]))',
        ),
        "panel-341": (
            "Trap Events Over Time",
            f'sum(count_over_time({device_trap} [$__interval]))',
        ),
        "panel-327": (
            "Ktranslate Logs",
            f'{LOKI_SVC} |= "$instance"',
        ),
    }

    for key, (_title, expr) in expr_map.items():
        panel = elements.get(key)
        if not panel:
            continue
        if set_loki_expr(panel, expr):
            changes.append(f"{key}: {expr[:90]}...")

    # panel-338 Trap Types — single dynamic TrapName query (match fleet summary)
    panel338 = elements.get("panel-338")
    if panel338:
        trap_types_expr = (
            f'sum by (TrapName) (count_over_time({device_trap} | TrapName != "" [$__range]))'
        )
        data = panel338["spec"]["data"]
        old_q = len(data["spec"]["queries"])
        template_q = copy.deepcopy(data["spec"]["queries"][0])
        qinner = template_q["spec"]["query"]["spec"]
        qinner["expr"] = trap_types_expr
        qinner["legendFormat"] = "{{TrapName}}"
        qinner["instant"] = True
        qinner["queryType"] = "instant"
        qinner["range"] = False
        data["spec"]["queries"] = [template_q]
        data["spec"]["transformations"] = [
            {
                "kind": "Transformation",
                "group": "partitionByValues",
                "spec": {
                    "options": {
                        "fields": ["TrapName"],
                        "naming": {"asLabels": True},
                    }
                },
            }
        ]
        panel338["spec"]["title"] = "Trap Types (range)"
        panel338["spec"]["description"] = (
            "SNMP trap events for this device (json eventType=KSnmpTrap, grouped by TrapName)."
        )
        viz = panel338["spec"]["vizConfig"]["spec"]
        viz.setdefault("fieldConfig", {}).setdefault("defaults", {})["displayName"] = (
            "${__field.labels.TrapName}"
        )
        changes.append(f"panel-338: collapsed {old_q} trap keyword queries -> TrapName json")

    desc_updates = {
        "panel-335": "Structured device syslog (instrumentation_name=ktranslate-syslog) for this device.",
        "panel-336": "Device syslog JSON events for this device — not collector internal logs.",
        "panel-337": "Structured SNMP traps (eventType=KSnmpTrap) for this device.",
        "panel-339": "Structured SNMP trap JSON for this device (eventType=KSnmpTrap).",
        "panel-340": "Device syslog volume over time (instrumentation_name=ktranslate-syslog).",
        "panel-341": "SNMP trap volume over time (eventType=KSnmpTrap).",
        "panel-327": (
            "All ktranslate log lines mentioning this device (syslog JSON, trap JSON, and internal "
            "plain-text). Use the Syslog and SNMP Traps rows above for typed views."
        ),
    }
    for key, desc in desc_updates.items():
        if key in elements:
            elements[key]["spec"]["description"] = desc

    return changes


def patch_device_summary(manifest: dict) -> list[str]:
    changes: list[str] = []
    elements = manifest.get("spec", {}).get("elements", {})

    if "panel-123" in elements:
        elements["panel-123"]["spec"]["title"] = "Syslog Collector Internal Logs"
        elements["panel-123"]["spec"]["description"] = (
            "ktranslate_syslog container operational logs (listener startup, device-list reloads). "
            "Not forwarded device syslog — use Recent Device Syslog for device messages."
        )
        if set_loki_expr(elements["panel-123"], SYSLOG_COLLECTOR_INTERNAL):
            changes.append("panel-123: clarified syslog collector internal logs")

    # Add fleet device-syslog panels if missing
    if "panel-144" not in elements:
        template = elements.get("panel-124") or elements.get("panel-123")
        if template:
            elements["panel-144"] = clone_panel(
                template,
                144,
                "Recent Device Syslog",
                "Forwarded device syslog (instrumentation_name=ktranslate-syslog). "
                "Structured JSON with severity, facility, and message.",
                SYSLOG_JSON,
            )
            changes.append("panel-144: added Recent Device Syslog")

    if "panel-145" not in elements:
        template = elements.get("panel-137")
        if template:
            elements["panel-145"] = clone_panel(
                template,
                145,
                "Syslog Volume by Severity",
                "Device syslog volume by RFC5424 severity (instrumentation_name=ktranslate-syslog).",
                (
                    f'sum by (severity) (count_over_time({SYSLOG_JSON} | severity != "" [$__interval]))'
                ),
            )
            elements["panel-145"]["spec"]["vizConfig"]["group"] = "timeseries"
            changes.append("panel-145: added Syslog Volume by Severity")

    # Insert Syslog row on Events tab (before Traps)
    layout = manifest.get("spec", {}).get("layout", {})
    tabs = layout.get("spec", {}).get("tabs", [])
    for tab in tabs:
        if tab.get("spec", {}).get("title") != "Events":
            continue
        rows = tab.get("spec", {}).get("layout", {}).get("spec", {}).get("rows", [])
        has_syslog_row = any(
            r.get("spec", {}).get("title") == "Device Syslog" for r in rows
        )
        if has_syslog_row:
            break
        syslog_row = {
            "kind": "RowsLayoutRow",
            "spec": {
                "title": "Device Syslog",
                "collapse": False,
                "hideHeader": False,
                "fillScreen": False,
                "layout": {
                    "kind": "GridLayout",
                    "spec": {
                        "items": [
                            {
                                "kind": "GridLayoutItem",
                                "spec": {
                                    "x": 0,
                                    "y": 0,
                                    "width": 14,
                                    "height": 12,
                                    "element": {
                                        "kind": "ElementReference",
                                        "name": "panel-144",
                                    },
                                },
                            },
                            {
                                "kind": "GridLayoutItem",
                                "spec": {
                                    "x": 14,
                                    "y": 0,
                                    "width": 10,
                                    "height": 12,
                                    "element": {
                                        "kind": "ElementReference",
                                        "name": "panel-145",
                                    },
                                },
                            },
                        ]
                    },
                },
            },
        }
        rows.insert(0, syslog_row)
        changes.append("Events tab: added Device Syslog row")
        break

    return changes


def patch_manifest(uid: str, manifest: dict) -> list[str]:
    if uid == "ktranslate-device-details":
        return patch_device_details(manifest)
    if uid == "ktranslate-device-summary":
        return patch_device_summary(manifest)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Patch locally only; no PUT")
    args = parser.parse_args()

    env = load_env()
    if not args.dry_run and (not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN")):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    out_dir = LIVE / "event-log-patched"
    out_dir.mkdir(parents=True, exist_ok=True)

    for uid in TARGETS:
        src = LIVE / f"{uid}.json"
        if not src.is_file():
            raise SystemExit(f"missing {src} — run reorganize pull first")
        manifest = json.loads(src.read_text(encoding="utf-8"))
        layout_before = manifest.get("spec", {}).get("layout", {}).get("kind")
        changes = patch_manifest(uid, manifest)
        layout_after = manifest.get("spec", {}).get("layout", {}).get("kind")
        if layout_before != layout_after:
            raise SystemExit(f"{uid}: layout kind changed {layout_before} -> {layout_after}")

        out_path = out_dir / f"{uid}.json"
        out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"\n{uid} ({layout_after}) — {len(changes)} change(s)")
        for c in changes:
            print(f"  - {c}")
        if not changes:
            print("  (no changes needed)")
            continue
        if not args.dry_run:
            put_dashboard(env, uid, manifest)
            gen = manifest.get("metadata", {}).get("generation", "?")
            print(f"  PUT ok -> {env['GRAFANA_URL'].rstrip('/')}/d/{uid} (gen was {gen})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
