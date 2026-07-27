#!/usr/bin/env python3
"""Add Country breakdown + Transport & ports rows to ktranslate-flow-summary (v2 RowsLayout).

Country panels use the same PromQL filters as the Geo Maps row (respects dashboard
variables; excludes Private IP / undefined). Does not hardcode mgmt CIDR.

For net-new dashboard design, prefer Grafana Assistant (GUI) or::

  gcx login
  gcx assistant dashboard "Add a country breakdown row to ktranslate-flow-summary ..."

``gcx assistant`` requires OAuth (not service-account tokens). Incremental v2 patches
here use ``gcx dashboards update`` / HTTP PUT to preserve RowsLayout.

Usage:
  python3 local/scripts/patch-flow-dashboard-sections.py --dry-run
  python3 local/scripts/patch-flow-dashboard-sections.py
  python3 local/scripts/patch-flow-dashboard-sections.py --fix-country
  python3 local/scripts/patch-flow-dashboard-sections.py --fix-transport
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "ktranslate-flow-sections-patched.json"
UID = "ktranslate-flow-summary"
NS = "stacks-1061129"
VIZ_VER = "13.2.0-29854286369"

FLOW_SEL = (
    'device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",'
    'network_peer_address=~"${dst_addr:pipe}",src_host=~"${src_host:pipe}",'
    'dst_host=~"${dst_host:pipe}",network_protocol_name=~"${application:pipe}"'
)
GEO_SEL = (
    f'network_io_by_flow_bytes{{{FLOW_SEL},network_peer_country!~"Private IP|undefined"}}'
)
ALL_SEL = f"network_io_by_flow_bytes{{{FLOW_SEL}}}"

NOTE = "Country breakdown + Transport & ports rows; country queries match Geo Maps filters."


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


def prom_query(expr: str, *, instant: bool = True, legend: str = "", table: bool = False) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "expr": expr,
        "queryType": "instant" if instant else "range",
        "instant": instant,
        "range": not instant,
    }
    if legend:
        spec["legendFormat"] = legend
    if table:
        spec["format"] = "table"
    return {
        "kind": "PanelQuery",
        "spec": {
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": {"name": "${datasource}"},
                "spec": spec,
            },
            "refId": "A",
            "hidden": False,
        },
    }


def table_viz(sort_field: str = "Total Bytes") -> dict[str, Any]:
    return {
        "kind": "VizConfig",
        "group": "table",
        "version": VIZ_VER,
        "spec": {
            "options": {
                "cellHeight": "sm",
                "enablePagination": True,
                "showHeader": True,
                "sortBy": [{"desc": True, "displayName": sort_field}],
            },
            "fieldConfig": {
                "defaults": {
                    "unit": "bytes",
                    "thresholds": {"mode": "percentage", "steps": [{"value": 0, "color": "green"}]},
                    "color": {"mode": "thresholds"},
                    "custom": {
                        "align": "auto",
                        "cellOptions": {"type": "auto"},
                        "footer": {"reducers": []},
                        "inspect": False,
                    },
                },
                "overrides": [
                    {
                        "matcher": {"id": "byName", "options": sort_field},
                        "properties": [
                            {
                                "id": "custom.cellOptions",
                                "value": {"mode": "lcd", "type": "gauge"},
                            }
                        ],
                    }
                ],
            },
        },
    }


def ports_table_viz() -> dict[str, Any]:
    """Port numbers are numeric — must not inherit table default unit=bytes."""
    sort_field = "Total Bytes"
    return {
        "kind": "VizConfig",
        "group": "table",
        "version": VIZ_VER,
        "spec": {
            "options": {
                "cellHeight": "sm",
                "enablePagination": True,
                "showHeader": True,
                "sortBy": [{"desc": True, "displayName": sort_field}],
            },
            "fieldConfig": {
                "defaults": {
                    "unit": "none",
                    "thresholds": {"mode": "percentage", "steps": [{"value": 0, "color": "green"}]},
                    "color": {"mode": "thresholds"},
                    "custom": {
                        "align": "auto",
                        "cellOptions": {"type": "auto"},
                        "footer": {"reducers": []},
                        "inspect": False,
                    },
                },
                "overrides": [
                    {
                        "matcher": {"id": "byName", "options": "Port"},
                        "properties": [
                            {"id": "unit", "value": "none"},
                            {"id": "decimals", "value": 0},
                        ],
                    },
                    {
                        "matcher": {"id": "byName", "options": "Application"},
                        "properties": [{"id": "unit", "value": "none"}],
                    },
                    {
                        "matcher": {"id": "byName", "options": sort_field},
                        "properties": [
                            {"id": "unit", "value": "bytes"},
                            {
                                "id": "custom.cellOptions",
                                "value": {"mode": "lcd", "type": "gauge"},
                            },
                        ],
                    },
                ],
            },
        },
    }


def pie_viz(link_label: str, link_field: str) -> dict[str, Any]:
    return {
        "kind": "VizConfig",
        "group": "piechart",
        "version": VIZ_VER,
        "spec": {
            "options": {
                "legend": {
                    "displayMode": "list",
                    "overflow": "ellipsis",
                    "placement": "right",
                    "showLegend": True,
                    "values": ["value"],
                },
                "pieType": "pie",
                "reduceOptions": {
                    "calcs": ["lastNotNull"],
                    "fields": "",
                    "limit": 10,
                    "values": False,
                },
                "sort": "desc",
                "tooltip": {"hideZeros": False, "mode": "single", "sort": "none"},
            },
            "fieldConfig": {
                "defaults": {
                    "unit": "bytes",
                    "color": {"mode": "palette-classic", "fixedColor": "#73BF69"},
                    "links": [
                        {
                            "targetBlank": False,
                            "title": link_label,
                            "url": link_field,
                        }
                    ],
                    "custom": {"hideFrom": {"legend": False, "tooltip": False, "viz": False}},
                },
                "overrides": [],
            },
        },
    }


def timeseries_viz() -> dict[str, Any]:
    return {
        "kind": "VizConfig",
        "group": "timeseries",
        "version": VIZ_VER,
        "spec": {
            "options": {
                "legend": {
                    "calcs": ["sum"],
                    "displayMode": "list",
                    "placement": "right",
                    "showLegend": True,
                },
                "tooltip": {"hideZeros": False, "mode": "multi", "sort": "desc"},
            },
            "fieldConfig": {
                "defaults": {
                    "unit": "bytes",
                    "color": {"mode": "palette-classic"},
                    "noValue": "0",
                    "custom": {
                        "drawStyle": "bars",
                        "fillOpacity": 80,
                        "stacking": {"group": "A", "mode": "normal"},
                        "lineWidth": 0,
                        "showPoints": "never",
                    },
                },
                "overrides": [],
            },
        },
    }


def make_panel(
    panel_id: int,
    title: str,
    description: str,
    expr: str,
    viz: dict[str, Any],
    *,
    instant: bool = True,
    legend: str = "",
    table: bool = False,
    transformations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "Panel",
        "spec": {
            "id": panel_id,
            "title": title,
            "description": description,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": [prom_query(expr, instant=instant, legend=legend, table=table)],
                    "transformations": transformations or [],
                    "queryOptions": {},
                },
            },
            "vizConfig": viz,
        },
    }


def grid_item(x: int, y: int, w: int, h: int, name: str) -> dict[str, Any]:
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


def layout_row(title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": "RowsLayoutRow",
        "spec": {
            "title": title,
            "collapse": False,
            "layout": {"kind": "GridLayout", "spec": {"items": items}},
        },
    }


def build_panels() -> dict[str, dict[str, Any]]:
    country_table_xform = [
        {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
        {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
        {
            "kind": "Transformation",
            "group": "organize",
            "spec": {
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "network_peer_country": 0,
                        "network_peer_address": 1,
                        "dst_host": 2,
                        "Value": 3,
                    },
                    "renameByName": {
                        "Value": "Bytes",
                        "network_peer_country": "Country",
                        "network_peer_address": "Peer IP",
                        "dst_host": "Peer Host",
                    },
                }
            },
        },
        {
            "kind": "Transformation",
            "group": "sortBy",
            "spec": {"options": {"sort": [{"desc": True, "field": "Bytes"}]}},
        },
    ]

    ports_table_xform = [
        {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
        {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
        {
            "kind": "Transformation",
            "group": "organize",
            "spec": {
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "network_peer_port": 0,
                        "network_protocol_name": 1,
                        "Value": 2,
                    },
                    "renameByName": {
                        "Value": "Total Bytes",
                        "network_peer_port": "Port",
                        "network_protocol_name": "Application",
                    },
                }
            },
        },
        {
            "kind": "Transformation",
            "group": "sortBy",
            "spec": {"options": {"sort": [{"desc": True, "field": "Total Bytes"}]}},
        },
    ]

    return {
        "panel-25": make_panel(
            25,
            "Peer Destinations by Country",
            "Drill-down for Geo Maps: country, peer IP, and hostname. Same filters as Top Flow Peer Locations.",
            f"topk(25, sum by(network_peer_country, network_peer_address, dst_host) "
            f"(max_over_time({GEO_SEL}[$__range])))",
            table_viz("Bytes"),
            table=True,
            transformations=country_table_xform,
        ),
        "panel-26": make_panel(
            26,
            "Peer Country Traffic over Time",
            "Stacked bytes by peer country (excludes Private IP / undefined). Matches Geo Maps variable scope.",
            f"sum by(network_peer_country) (max_over_time({GEO_SEL}[$__rate_interval]))",
            timeseries_viz(),
            instant=False,
            legend="{{network_peer_country}}",
        ),
        "panel-27": make_panel(
            27,
            "Traffic by Transport",
            "TCP vs UDP share of flow bytes (all matched flows).",
            f"sum by(network_transport) (max_over_time({ALL_SEL}[$__range]))",
            pie_viz(
                "Filter transport",
                "/d/${__dashboard.uid}/${__dashboard.name}?from=${__from}&to=${__to}&timezone=browser"
                "&${device_name:queryparam}&${src_addr:queryparam}&${dst_addr:queryparam}"
                "&${application:queryparam}",
            ),
            legend="{{network_transport}}",
        ),
        "panel-28": make_panel(
            28,
            "Top Destination Ports",
            "Peer port and L7 application (ktranslate protocol name).",
            f"topk(20, sum by(network_peer_port, network_protocol_name) "
            f"(max_over_time({ALL_SEL}[$__range])))",
            ports_table_viz(),
            table=True,
            transformations=ports_table_xform,
        ),
    }


def reorder_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place Country Breakdown immediately after Geo Maps."""
    by_title: dict[str, dict[str, Any]] = {}
    rest: list[dict[str, Any]] = []
    for row in rows:
        title = row.get("spec", row).get("title", "")
        if title in ("Country Breakdown", "Transport & Ports"):
            by_title[title] = row
        else:
            rest.append(row)
    out: list[dict[str, Any]] = []
    for row in rest:
        out.append(row)
        if row.get("spec", row).get("title") == "Geo Maps":
            if "Country Breakdown" in by_title:
                out.append(by_title["Country Breakdown"])
    if "Transport & Ports" in by_title:
        out.append(by_title["Transport & Ports"])
    return out


def patch_dashboard(
    dash: dict, *, fix_country: bool = False, fix_transport: bool = False
) -> dict:
    out = copy.deepcopy(dash)
    spec = out.setdefault("spec", {})
    elements = spec.setdefault("elements", {})
    panels = build_panels()

    if fix_country or fix_transport or "panel-25" not in elements:
        if fix_country or "panel-25" not in elements:
            elements["panel-25"] = panels["panel-25"]
            elements["panel-26"] = panels["panel-26"]
        if fix_transport or "panel-27" not in elements:
            elements["panel-27"] = panels["panel-27"]
            elements["panel-28"] = panels["panel-28"]
    elif "panel-25" in elements:
        # Refresh country panel queries/transforms (fix bad 172.20.20.* patch).
        elements["panel-25"] = panels["panel-25"]
        elements["panel-26"] = panels["panel-26"]
        if "panel-27" not in elements:
            elements["panel-27"] = panels["panel-27"]
            elements["panel-28"] = panels["panel-28"]

    rows = spec.setdefault("layout", {}).setdefault("spec", {}).setdefault("rows", [])
    row_titles = {r.get("spec", r).get("title") for r in rows}
    if "Country Breakdown" not in row_titles:
        rows.append(
            layout_row(
                "Country Breakdown",
                [
                    grid_item(0, 0, 10, 12, "panel-25"),
                    grid_item(10, 0, 14, 12, "panel-26"),
                ],
            )
        )
    if "Transport & Ports" not in row_titles:
        rows.append(
            layout_row(
                "Transport & Ports",
                [
                    grid_item(0, 0, 8, 10, "panel-27"),
                    grid_item(8, 0, 16, 10, "panel-28"),
                ],
            )
        )
    spec["layout"]["spec"]["rows"] = reorder_rows(rows)

    ann = out.setdefault("metadata", {}).setdefault("annotations", {})
    msg = ann.get("grafana.app/message", "")
    if NOTE not in msg:
        ann["grafana.app/message"] = (msg.rstrip() + "\n" + NOTE).strip()
    return out


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--fix-country",
        action="store_true",
        help="Update country panel queries even if panel-25 already exists",
    )
    ap.add_argument(
        "--fix-transport",
        action="store_true",
        help="Refresh Transport & Ports panels (port column unit + transforms)",
    )
    args = ap.parse_args()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    dash = get_dashboard(env)
    gen = dash.get("metadata", {}).get("generation", "?")
    layout = dash.get("spec", {}).get("layout", {}).get("kind")
    print(f"Fetched {UID} generation={gen} layout={layout}")

    patched = patch_dashboard(
        dash, fix_country=args.fix_country, fix_transport=args.fix_transport
    )
    OUT.write_text(json.dumps(patched, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")

    if args.dry_run:
        print("dry-run: not pushing")
        return 0

    put_dashboard(env, patched)
    print(f"Patched {env['GRAFANA_URL'].rstrip('/')}/d/{UID}")
    print(f"layout={patched.get('spec', {}).get('layout', {}).get('kind')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
