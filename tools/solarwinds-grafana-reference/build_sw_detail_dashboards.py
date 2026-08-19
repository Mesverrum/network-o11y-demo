#!/usr/bin/env python3
"""Build + push SW detail clones: Interface, Volume, Application, Component, Alert.

Mirrors Orion classic detail views with TabsLayout (when multi-tab), StatusInfo
color mappings, hidden *ID columns, and entity pickers (no redundant host spam).
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from sw_dashboard_links import LINK_ID_FIELDS, dashboard_nav_links, merge_table_overrides

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "out" / "latest" / "raw" / "classic-views"
STATUSINFO_PATH = ROOT / "swql_library" / "statusinfo.json"
DS_UID = "cfuwljtvzdclcb"
DS_TYPE = "grafana-solarwinds-datasource"
FOLDER_UID = "cf8311my2in7kf"
NS = "stacks-1061129"

HIDE_FIELD_REGEXP = (
    r"(?i)^(AlertObjectID|AlertID|"
    r"EventID|DependencyID|NetObjectID|AuditEventID|"
    r"AccountID|ActionTypeID|EngineID|Id|MapID|PortID)$"
)


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def grafana_creds() -> tuple[str, str]:
    env: dict[str, str] = {}
    for p in (
        ROOT.parents[1] / "local" / ".env",
        Path(r"C:\Users\mesve\projects\network-o11y-demo\local\.env"),
    ):
        env.update(load_env_file(p))
    url = os.environ.get("GRAFANA_URL") or env.get("GRAFANA_URL") or ""
    token = os.environ.get("GRAFANA_TOKEN") or env.get("GRAFANA_TOKEN") or ""
    if not url or not token:
        raise SystemExit("Need GRAFANA_URL + GRAFANA_TOKEN in local/.env")
    return url.rstrip("/"), token


def api(method: str, path: str, token: str, base: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}{path}",
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
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {e.code} {path}: {detail}") from e


def swis_query(sw_env: dict[str, str], swql: str) -> tuple[list[dict] | None, str | None]:
    import base64

    token = base64.b64encode(f"{sw_env['SW_USER']}:{sw_env['SW_PASSWORD']}".encode()).decode()
    port = int(sw_env.get("SW_PORT") or "17774")
    body = json.dumps({"query": swql}).encode()
    req = urllib.request.Request(
        f"https://{sw_env['SW_HOST']}:{port}/SolarWinds/InformationService/v3/Json/Query",
        data=body,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=60) as resp:
            return json.loads(resp.read().decode()).get("results") or [], None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def load_statusinfo() -> list[dict[str, Any]]:
    if STATUSINFO_PATH.exists():
        data = json.loads(STATUSINFO_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    return []


def status_value_mappings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    options: dict[str, Any] = {}
    for i, row in enumerate(rows):
        sid = row.get("StatusId")
        if sid is None:
            continue
        name = row.get("ShortDescription") or row.get("StatusName") or str(sid)
        color = row.get("Color") or "#999999"
        options[str(sid)] = {"text": str(name), "color": color, "index": i}
        for key in ("StatusName", "ShortDescription"):
            val = row.get(key)
            if val and str(val) not in options:
                options[str(val)] = {"text": str(name), "color": color, "index": i}
    return [{"type": "value", "options": options}]


def status_field_overrides(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mappings = status_value_mappings(rows)
    return [
        {
            "matcher": {"id": "byRegexp", "options": HIDE_FIELD_REGEXP},
            "properties": [{"id": "custom.hidden", "value": True}],
        },
        {
            "matcher": {"id": "byName", "options": "Status"},
            "properties": [
                {"id": "mappings", "value": mappings},
                {
                    "id": "custom.cellOptions",
                    "value": {"type": "color-background", "mode": "basic"},
                },
                {"id": "custom.width", "value": 140},
            ],
        },
    ]


def table_transforms_hide_ids() -> list[dict[str, Any]]:
    # Keep LINK_ID_FIELDS in the frame (hidden via fieldConfig) for data links.
    exclude = {
        k: True
        for k in (
            "AlertObjectID",
            "AlertID",
            "EventID",
            "NetObjectID",
            "EngineID",
            "Id",
            "ApplicationTemplateID",
        )
        if k not in LINK_ID_FIELDS
    }
    return [{"id": "organize", "options": {"excludeByName": exclude, "indexByName": {}, "renameByName": {}}}]


def sw_query(swql: str) -> dict[str, Any]:
    return {
        "kind": "PanelQuery",
        "spec": {
            "query": {
                "kind": "DataQuery",
                "group": DS_TYPE,
                "version": "v0",
                "datasource": {"name": DS_UID},
                "spec": {
                    "params": {"query": swql},
                    "queryType": "swql_query",
                    "serviceId": "solarwinds",
                },
            },
            "refId": "A",
            "hidden": False,
        },
    }


def table_panel(pid: int, title: str, swql: str, description: str, status_rows: list) -> dict:
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
                    "queries": [sw_query(swql)],
                    "transformations": table_transforms_hide_ids(),
                    "queryOptions": {},
                },
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": "table",
                "version": "",
                "spec": {
                    "options": {"cellHeight": "sm", "showHeader": True},
                    "fieldConfig": {
                        "defaults": {"custom": {"align": "auto", "filterable": True}},
                        "overrides": merge_table_overrides(
                            status_field_overrides(status_rows), swql=swql, title=title
                        ),
                    },
                },
            },
        },
    }


def timeseries_panel(
    pid: int,
    title: str,
    swql: str,
    description: str,
    *,
    unit: str = "",
    time_field: str = "DateTime",
) -> dict:
    """History SWQL → timeseries. Plugin returns DateTime as string; convert to time."""
    defaults: dict[str, Any] = {
        "custom": {
            "drawStyle": "line",
            "lineInterpolation": "smooth",
            "showPoints": "never",
            "fillOpacity": 10,
            "spanNulls": False,
        },
        "color": {"mode": "palette-classic"},
    }
    if unit:
        defaults["unit"] = unit
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
                    "queries": [sw_query(swql)],
                    "transformations": [
                        {
                            "id": "convertFieldType",
                            "options": {
                                "conversions": [
                                    {
                                        "targetField": time_field,
                                        "destinationType": "time",
                                    }
                                ]
                            },
                        }
                    ],
                    "queryOptions": {},
                },
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": "timeseries",
                "version": "",
                "spec": {
                    "options": {
                        "legend": {
                            "displayMode": "list",
                            "placement": "bottom",
                            "showLegend": True,
                        },
                        "tooltip": {"mode": "multi", "sort": "desc"},
                    },
                    "fieldConfig": {"defaults": defaults, "overrides": []},
                },
            },
        },
    }


def markdown_panel(pid: int, title: str, content: str) -> dict:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": "Orion UI / chrome widget",
            "links": [],
            "data": {"kind": "QueryGroup", "spec": {"queries": [], "transformations": [], "queryOptions": {}}},
            "vizConfig": {
                "kind": "VizConfig",
                "group": "text",
                "version": "",
                "spec": {
                    "options": {"mode": "markdown", "content": content},
                    "fieldConfig": {"defaults": {}, "overrides": []},
                },
            },
        },
    }


def stat_panel(pid: int, title: str, swql: str, *, status_rows: list | None = None, status_field: bool = False) -> dict:
    defaults: dict[str, Any] = {
        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]}
    }
    if status_field and status_rows:
        defaults["mappings"] = status_value_mappings(status_rows)
        steps = [{"color": "#999999", "value": None}]
        for row in sorted(status_rows, key=lambda r: r.get("StatusId") or 0):
            sid = row.get("StatusId")
            if sid is None:
                continue
            steps.append({"color": row.get("Color") or "#999999", "value": sid})
        defaults["thresholds"] = {"mode": "absolute", "steps": steps}
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": [sw_query(swql)], "transformations": [], "queryOptions": {}},
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": "stat",
                "version": "",
                "spec": {
                    "options": {
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "background",
                        "graphMode": "none",
                        "justifyMode": "auto",
                        "textMode": "auto",
                    },
                    "fieldConfig": {"defaults": defaults, "overrides": []},
                },
            },
        },
    }


def grid_item(x: int, y: int, w: int, h: int, name: str) -> dict:
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


def load_view_tabs(group_paths: list[Path]) -> list[dict[str, Any]]:
    tabs: list[dict[str, Any]] = []
    for path in group_paths:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        resources = data.get("resources") or []
        resources = sorted(
            resources,
            key=lambda r: (
                r.get("viewColumn") if r.get("viewColumn") is not None else 99,
                r.get("position") if r.get("position") is not None else 999,
                r.get("resourceTitle") or "",
            ),
        )
        tabs.append(
            {
                "viewTitle": data.get("viewTitle") or path.parent.name,
                "viewId": data.get("viewId"),
                "viewKey": data.get("viewKey"),
                "resources": resources,
            }
        )
    # Summary first
    tabs.sort(key=lambda t: (0 if t["viewTitle"] == "Summary" else 1, t["viewTitle"] or ""))
    return tabs


# ---------------------------------------------------------------------------
# Per-entity SWQL guessers
# ---------------------------------------------------------------------------

from sw_detail_guesses import (
    A,
    AL,
    C,
    I,
    V,
    guess_alert,
    guess_application,
    guess_component,
    guess_interface,
    guess_volume,
)


DetailDef = dict[str, Any]


DETAILS: list[DetailDef] = [
    {
        "uid": "sw-interface-details",
        "title": "SW: Interface Details",
        "tag": "interface-details",
        "var_name": "interface_id",
        "var_label": "Interface",
        "var_query": "SELECT InterfaceID, Caption FROM Orion.NPM.Interfaces ORDER BY Caption",
        "var_text": "Caption",
        "var_value": "InterfaceID",
        "orion_link": "http://3.88.155.134:8787/Orion/NetPerfMon/InterfaceDetails.aspx?NetObject=I%3A${interface_id}",
        "views": [
            RAW / "Interface Details" / "Summary" / "view.json",
            RAW / "Interface Details" / "Map" / "view.json",
        ],
        "guess": guess_interface,
        "stub": f"SELECT Caption, Status, StatusDescription, InPercentUtil, OutPercentUtil FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}",
        "header_stats": [
            ("Status", f"SELECT Status FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}", True),
            ("In Util %", f"SELECT InPercentUtil FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}", False),
            ("Out Util %", f"SELECT OutPercentUtil FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}", False),
            ("In bps", f"SELECT Inbps FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}", False),
            ("Out bps", f"SELECT Outbps FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}", False),
        ],
    },
    {
        "uid": "sw-volume-details",
        "title": "SW: Volume Details",
        "tag": "volume-details",
        "var_name": "volume_id",
        "var_label": "Volume",
        "var_query": "SELECT VolumeID, Caption FROM Orion.Volumes ORDER BY Caption",
        "var_text": "Caption",
        "var_value": "VolumeID",
        "orion_link": "http://3.88.155.134:8787/Orion/NetPerfMon/VolumeDetails.aspx?NetObject=V%3A${volume_id}",
        "views": [
            RAW / "Volume Details" / "Summary" / "view.json",
            RAW / "Volume Details" / "Map" / "view.json",
        ],
        "guess": guess_volume,
        "stub": f"SELECT Caption, Status, StatusDescription, VolumePercentUsed, VolumeSize FROM Orion.Volumes WHERE VolumeID = {V}",
        "header_stats": [
            ("Status", f"SELECT Status FROM Orion.Volumes WHERE VolumeID = {V}", True),
            ("% Used", f"SELECT VolumePercentUsed FROM Orion.Volumes WHERE VolumeID = {V}", False),
            ("Size", f"SELECT VolumeSize FROM Orion.Volumes WHERE VolumeID = {V}", False),
            ("Used", f"SELECT VolumeSpaceUsed FROM Orion.Volumes WHERE VolumeID = {V}", False),
            ("Free", f"SELECT VolumeSpaceAvailable FROM Orion.Volumes WHERE VolumeID = {V}", False),
        ],
    },
    {
        "uid": "sw-application-details",
        "title": "SW: Application Details",
        "tag": "application-details",
        "var_name": "application_id",
        "var_label": "Application",
        "var_query": "SELECT ApplicationID, Name FROM Orion.APM.Application ORDER BY Name",
        "var_text": "Name",
        "var_value": "ApplicationID",
        "orion_link": "http://3.88.155.134:8787/Orion/APM/ApplicationDetails.aspx?NetObject=AA%3A${application_id}",
        "views": [
            RAW / "Application Details" / "Summary" / "view.json",
            RAW / "Application Details" / "Map" / "view.json",
        ],
        "guess": guess_application,
        "stub": f"SELECT Name, Status, StatusDescription FROM Orion.APM.Application WHERE ApplicationID = {A}",
        "header_stats": [
            ("Status", f"SELECT Status FROM Orion.APM.Application WHERE ApplicationID = {A}", True),
        ],
    },
    {
        "uid": "sw-component-details",
        "title": "SW: Component Details",
        "tag": "component-details",
        "var_name": "component_id",
        "var_label": "Component",
        "var_query": "SELECT ComponentID, Name FROM Orion.APM.Component ORDER BY Name",
        "var_text": "Name",
        "var_value": "ComponentID",
        "orion_link": "http://3.88.155.134:8787/Orion/APM/MonitorDetails.aspx?NetObject=AM%3A${component_id}",
        "views": [RAW / "NoViewGroup" / "Application Component Details" / "view.json"],
        "guess": guess_component,
        "stub": f"SELECT Name, Status FROM Orion.APM.Component WHERE ComponentID = {C}",
        "header_stats": [
            ("Status", f"SELECT Status FROM Orion.APM.Component WHERE ComponentID = {C}", True),
        ],
    },
    {
        "uid": "sw-alert-details",
        "title": "SW: Alert Details",
        "tag": "alert-details",
        "var_name": "alert_active_id",
        "var_label": "Active Alert",
        "var_query": (
            "SELECT aa.AlertActiveID, a.Name "
            "FROM Orion.AlertActive aa "
            "JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            "JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
            "ORDER BY aa.TriggeredDateTime DESC"
        ),
        "var_text": "Name",
        "var_value": "AlertActiveID",
        "orion_link": "http://3.88.155.134:8787/Orion/NetPerfMon/ActiveAlertDetails.aspx?NetObject=AAT%3A${alert_active_id}",
        "views": [RAW / "NoViewGroup" / "Active Alert Details" / "view.json"],
        "guess": guess_alert,
        "stub": (
            f"SELECT a.Name AS AlertName, aa.TriggeredMessage, aa.TriggeredDateTime, o.EntityCaption "
            f"FROM Orion.AlertActive aa "
            f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            f"JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
            f"WHERE aa.AlertActiveID = {AL}"
        ),
        "header_stats": [],
    },
]


def build_var_options(rows: list[dict], text_key: str, value_key: str) -> tuple[str, dict, list]:
    options = []
    current = None
    for r in rows:
        text = str(r.get(text_key) or r.get(value_key))
        value = str(r.get(value_key))
        opt = {"text": text, "value": value, "selected": False}
        options.append(opt)
        if current is None:
            current = opt
            opt["selected"] = True
    if not options:
        raise SystemExit(f"No options for {value_key}")
    query_text = ",".join(f"{o['text']} : {o['value']}" for o in options)
    return query_text, current, options


def build_manifest(defn: DetailDef, entities: list[dict], status_rows: list) -> dict[str, Any]:
    tabs_src = load_view_tabs(defn["views"])
    if not tabs_src:
        raise SystemExit(f"No views for {defn['uid']}")

    query_text, current, options = build_var_options(entities, defn["var_text"], defn["var_value"])
    guess: Callable = defn["guess"]
    stub = defn["stub"]

    elements: dict[str, Any] = {}
    tabs: list[dict] = []
    pid = 1

    for tab in tabs_src:
        title = tab["viewTitle"]
        resources = list(tab.get("resources") or [])
        items: list[dict] = []
        col_y = {1: 0, 2: 0, 3: 0}

        if title == "Summary" and defn.get("header_stats"):
            stats = defn["header_stats"]
            width = max(4, 24 // max(len(stats), 1))
            x = 0
            for st_title, swql, is_status in stats:
                el = f"panel-{pid}"
                elements[el] = stat_panel(
                    pid, st_title, swql, status_rows=status_rows, status_field=is_status
                )
                w = width if x + width <= 24 else 24 - x
                items.append(grid_item(x, 0, w, 4, el))
                x += w
                pid += 1
            col_y = {1: 4, 2: 4, 3: 4}

        if not resources:
            el = f"panel-{pid}"
            elements[el] = markdown_panel(
                pid,
                f"{title} — empty export",
                f"Orion view **{title}** exported with 0 resources (map/chrome).",
            )
            items.append(grid_item(0, col_y[1], 24, 4, el))
            pid += 1
        else:
            for r in resources:
                rtitle = r.get("resourceTitle") or r.get("resourceName") or f"widget-{pid}"
                rname = r.get("resourceName") or ""
                rfile = r.get("resourceFile") or ""
                col = int(r.get("viewColumn") or 1)
                if col not in (1, 2, 3):
                    col = 1
                # 3-col layout for alerts; 2-col otherwise
                if max((x.get("viewColumn") or 1) for x in resources) >= 3:
                    x = {1: 0, 2: 8, 3: 16}[col]
                    w = 8
                else:
                    x = {1: 0, 2: 12, 3: 0}[col]
                    w = 12

                swql, note, viz = guess(rtitle, rname, rfile)
                el = f"panel-{pid}"
                if swql is None or viz == "markdown":
                    elements[el] = markdown_panel(
                        pid,
                        rtitle,
                        f"**{rtitle}**\n\n{note}\n\nOrion file: `{rfile}`",
                    )
                    h = 5
                elif viz.startswith("timeseries"):
                    unit = viz.split(":", 1)[1] if ":" in viz else ""
                    elements[el] = timeseries_panel(
                        pid, rtitle, swql, f"Orion history · {note}", unit=unit
                    )
                    h = 10
                else:
                    elements[el] = table_panel(
                        pid, rtitle, swql, f"Orion guess · {note}", status_rows
                    )
                    h = 8
                items.append(grid_item(x, col_y[col], w, h, el))
                col_y[col] += h
                pid += 1

        tabs.append(
            {
                "kind": "TabsLayoutTab",
                "spec": {
                    "title": title if title != "Application Component Details" else "Summary",
                    "layout": {"kind": "GridLayout", "spec": {"items": items}},
                },
            }
        )

    # If Active Alert Details is a single view, rename tab to Summary
    if len(tabs) == 1 and tabs[0]["spec"]["title"] not in {"Summary", "Map"}:
        tabs[0]["spec"]["title"] = "Summary"

    return {
        "kind": "Dashboard",
        "apiVersion": "dashboard.grafana.app/v2",
        "metadata": {
            "name": defn["uid"],
            "annotations": {
                "grafana.app/folder": FOLDER_UID,
                "grafana.app/message": f"Upsert {defn['title']} Orion clone",
            },
        },
        "spec": {
            "title": defn["title"],
            "description": (
                f"Clone of Orion {defn['title'].replace('SW: ', '')}. "
                f"Datasource AWS-SolarWinds ({DS_UID}). Variable ${defn['var_name']}."
            ),
            "tags": ["solarwinds", "clone", defn["tag"], "network-o11y", "tabs"],
            "editable": True,
            "preload": False,
            "liveNow": False,
            "cursorSync": "Crosshair",
            "links": [
                {
                    "title": "Open in Orion",
                    "type": "link",
                    "icon": "external link",
                    "tooltip": "",
                    "url": defn["orion_link"],
                    "tags": [],
                    "asDropdown": False,
                    "targetBlank": True,
                    "includeVars": False,
                    "keepTime": False,
                },
                *dashboard_nav_links(defn["uid"]),
            ],
            "annotations": [],
            "variables": [
                {
                    "kind": "CustomVariable",
                    "spec": {
                        "name": defn["var_name"],
                        "label": defn["var_label"],
                        "query": query_text,
                        "current": {"text": current["text"], "value": current["value"]},
                        "options": options,
                        "multi": False,
                        "includeAll": False,
                        "hide": "dontHide",
                        "skipUrlSync": False,
                        "allowCustomValue": True,
                    },
                }
            ],
            "timeSettings": {
                "timezone": "browser",
                "from": "now-2y",
                "to": "now",
                "autoRefresh": "1m",
                "autoRefreshIntervals": ["30s", "1m", "5m", "15m", "1h"],
                "hideTimepicker": False,
                "fiscalYearStartMonth": 0,
            },
            "elements": elements,
            "layout": {"kind": "TabsLayout", "spec": {"tabs": tabs}},
        },
    }


def validate_and_fix_manifest(manifest: dict, sw_env: dict, stub: str, sample_id: str) -> None:
    """Replace failing SWQL panels with stub (template var → sample id for test)."""
    elements = manifest["spec"]["elements"]
    for name, el in list(elements.items()):
        if el.get("kind") != "Panel":
            continue
        viz = (el.get("spec") or {}).get("vizConfig", {}).get("group")
        if viz != "table":
            continue
        queries = (
            el.get("spec", {})
            .get("data", {})
            .get("spec", {})
            .get("queries")
            or []
        )
        if not queries:
            continue
        qspec = queries[0]["spec"]["query"]["spec"]
        swql = qspec["params"]["query"]
        concrete = re.sub(r"\$\w+", sample_id, swql)
        concrete = concrete.replace("${interface_id}", sample_id).replace("${volume_id}", sample_id)
        concrete = concrete.replace("${application_id}", sample_id).replace("${component_id}", sample_id)
        concrete = concrete.replace("${alert_active_id}", sample_id)
        _, err = swis_query(sw_env, concrete)
        if err:
            print(f"  fix {el['spec'].get('title')}: {err[:60]}")
            # keep template vars in stub
            qspec["params"]["query"] = stub
            el["spec"]["description"] = (el["spec"].get("description") or "") + f" · SWIS fail→stub ({err[:80]})"


def upsert(manifest: dict, base: str, token: str) -> None:
    uid = manifest["metadata"]["name"]
    get_path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    try:
        status, existing = api("GET", get_path, token, base)
    except RuntimeError as e:
        if "HTTP 404" not in str(e):
            raise
        status, existing = 404, {}
    if status == 200:
        emeta = existing.get("metadata") or {}
        manifest["metadata"]["resourceVersion"] = emeta.get("resourceVersion")
        elabels = emeta.get("labels") or {}
        if "grafana.app/deprecatedInternalID" in elabels:
            manifest.setdefault("metadata", {}).setdefault("labels", {})[
                "grafana.app/deprecatedInternalID"
            ] = elabels["grafana.app/deprecatedInternalID"]
        status, resp = api("PUT", get_path, token, base, manifest)
        print(f"  PUT {uid} HTTP {status} gen={resp.get('metadata', {}).get('generation')} layout={resp.get('spec', {}).get('layout', {}).get('kind')}")
    else:
        status, resp = api(
            "POST",
            f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards",
            token,
            base,
            manifest,
        )
        print(f"  POST {uid} HTTP {status} layout={resp.get('spec', {}).get('layout', {}).get('kind')}")
    print(f"  Open: {base}/d/{uid}/")


def main() -> int:
    sw_env = load_env_file(ROOT / "swis.env")
    status_rows = load_statusinfo()
    base, token = grafana_creds()
    out_dir = ROOT / "out" / "latest" / "grafana"
    out_dir.mkdir(parents=True, exist_ok=True)

    for defn in DETAILS:
        print(f"\n=== {defn['title']} ===")
        entities, err = swis_query(sw_env, defn["var_query"])
        if err or not entities:
            print(f"  SKIP: cannot load entities: {err}")
            continue
        sample_id = str(entities[0][defn["var_value"]])
        manifest = build_manifest(defn, entities, status_rows)
        print(f"  panels={len(manifest['spec']['elements'])} tabs={len(manifest['spec']['layout']['spec']['tabs'])} entities={len(entities)}")
        print("  validating SWQL…")
        validate_and_fix_manifest(manifest, sw_env, defn["stub"], sample_id)
        path = out_dir / f"{defn['uid']}.v2.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  wrote {path}")
        upsert(manifest, base, token)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
