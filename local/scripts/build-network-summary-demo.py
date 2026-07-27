#!/usr/bin/env python3
"""Flesh out marcnetterfield1 Network Summary dashboard with anonymous demo data.

Uses grafana-testdata-datasource for CMDB / ITSM visuals. Device and site
names are generic production-style labels (no customer-specific identifiers).
Panel styling follows ktranslate fleet dashboards (stat + bargauge + timeseries).

Fetch → patch v2 manifest → gcx dashboards update (preserves RowsLayout).
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

UID = "fbb764ab-402e-4411-9398-ac2974ce5dc6"
TESTDATA = "de1z0n8fujvggb"
VIZ_VER = "12.3.0-18686767985.patch2"
SANKEY_VER = "1.1.3"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
SANKEY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "network-summary-sankey-panel.json"


def gcx_get() -> dict:
    raw = subprocess.check_output(
        ["gcx", "--context", "marcnetterfield1", "dashboards", "get", UID, "-o", "json"],
        stderr=subprocess.DEVNULL,
    ).decode("utf-8", errors="replace")
    return json.loads(raw[raw.find("{") :])


def gcx_update(dash: dict) -> None:
    out = Path("/tmp/network-summary-patched.json")
    out.write_text(json.dumps(dash, indent=2), encoding="utf-8")
    subprocess.run(
        ["gcx", "--context", "marcnetterfield1", "dashboards", "update", UID, "-f", str(out)],
        check=True,
    )


def td_query(ref: str, scenario: str, **kw) -> dict:
    return {
        "kind": "PanelQuery",
        "spec": {
            "hidden": False,
            "query": {
                "datasource": {"name": TESTDATA},
                "group": "grafana-testdata-datasource",
                "kind": "DataQuery",
                "spec": {"scenarioId": scenario, **kw},
                "version": "v0",
            },
            "refId": ref,
        },
    }


def csv_content_query(ref: str, rows: list[dict], fieldnames: list[str]) -> dict:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    return td_query(ref, "csv_content", csvContent=buf.getvalue())


def stat_panel(
    pid: int,
    title: str,
    queries: list[dict],
    *,
    desc: str = "",
    color_mode: str = "background",
    text_mode: str = "name",
    reduce_fields: str = "",
    unit: str = "",
    thresholds: list[dict] | None = None,
    links: list[dict] | None = None,
    overrides: list[dict] | None = None,
) -> dict:
    steps = thresholds or [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 90},
        {"color": "green", "value": 95},
    ]
    defaults: dict = {
        "color": {"mode": "thresholds"},
        "thresholds": {"mode": "absolute", "steps": steps},
    }
    if unit:
        defaults["unit"] = unit
    if links:
        defaults["links"] = links
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": desc,
            "links": links or [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": queries, "queryOptions": {}, "transformations": []},
            },
            "vizConfig": {
                "group": "stat",
                "kind": "VizConfig",
                "version": VIZ_VER,
                "spec": {
                    "fieldConfig": {
                        "defaults": defaults,
                        "overrides": overrides or [],
                    },
                    "options": {
                        "colorMode": color_mode,
                        "graphMode": "area",
                        "justifyMode": "auto",
                        "orientation": "auto",
                        "percentChangeColorMode": "standard",
                        "reduceOptions": {
                            "calcs": ["lastNotNull"],
                            "fields": reduce_fields,
                            "values": True,
                        },
                        "showPercentChange": False,
                        "text": {"titleSize": 14, "valueSize": 20},
                        "textMode": text_mode,
                        "wideLayout": True,
                    },
                },
            },
        },
    }


def table_panel(
    pid: int,
    title: str,
    query: dict,
    *,
    desc: str = "",
    sort_col: str = "",
    overrides: list[dict] | None = None,
) -> dict:
    sort_by = [{"desc": True, "displayName": sort_col}] if sort_col else []
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": desc,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": [query], "queryOptions": {}, "transformations": []},
            },
            "vizConfig": {
                "group": "table",
                "kind": "VizConfig",
                "version": VIZ_VER,
                "spec": {
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "custom": {
                                "align": "auto",
                                "cellOptions": {"type": "auto"},
                                "footer": {"reducers": []},
                                "inspect": False,
                            },
                            "thresholds": {
                                "mode": "absolute",
                                "steps": [
                                    {"color": "green", "value": None},
                                    {"color": "red", "value": 80},
                                ],
                            },
                        },
                        "overrides": overrides or [],
                    },
                    "options": {
                        "cellHeight": "sm",
                        "showHeader": True,
                        "sortBy": sort_by,
                    },
                },
            },
        },
    }


def text_panel(pid: int, title: str, content: str, *, h_note: str = "") -> dict:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": h_note,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": [], "queryOptions": {}, "transformations": []},
            },
            "vizConfig": {
                "group": "text",
                "kind": "VizConfig",
                "version": VIZ_VER,
                "spec": {
                    "fieldConfig": {"defaults": {}, "overrides": []},
                    "options": {
                        "mode": "markdown",
                        "content": content,
                        "code": {
                            "language": "plaintext",
                            "showLineNumbers": False,
                            "showMiniMap": False,
                        },
                    },
                },
            },
        },
    }


def grid_item(name: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "kind": "GridLayoutItem",
        "spec": {
            "element": {"kind": "ElementReference", "name": name},
            "x": x,
            "y": y,
            "width": w,
            "height": h,
        },
    }


def row_layout(title: str, items: list[dict], *, hide_header: bool = False) -> dict:
    return {
        "kind": "RowsLayoutRow",
        "spec": {
            "title": title,
            "collapse": False,
            "hideHeader": hide_header,
            "layout": {
                "kind": "GridLayout",
                "spec": {"items": items},
            },
        },
    }


def severity_override(col: str) -> dict:
    return {
        "matcher": {"id": "byName", "options": col},
        "properties": [
            {
                "id": "custom.cellOptions",
                "value": {
                    "type": "color-text",
                    "mode": "gradient",
                },
            },
            {
                "id": "mappings",
                "value": [
                    {"type": "value", "options": {"Critical": {"color": "red", "index": 0}}},
                    {"type": "value", "options": {"High": {"color": "orange", "index": 1}}},
                    {"type": "value", "options": {"Warning": {"color": "yellow", "index": 2}}},
                    {"type": "value", "options": {"Medium": {"color": "yellow", "index": 3}}},
                    {"type": "value", "options": {"Low": {"color": "green", "index": 4}}},
                ],
            },
        ],
    }


def status_override(col: str) -> dict:
    return {
        "matcher": {"id": "byName", "options": col},
        "properties": [
            {
                "id": "mappings",
                "value": [
                    {"type": "value", "options": {"up": {"color": "green", "index": 0}}},
                    {"type": "value", "options": {"down": {"color": "red", "index": 1}}},
                    {"type": "value", "options": {"degraded": {"color": "yellow", "index": 2}}},
                    {"type": "value", "options": {"established": {"color": "green", "index": 0}}},
                    {"type": "value", "options": {"active": {"color": "red", "index": 1}}},
                    {"type": "value", "options": {"idle": {"color": "yellow", "index": 2}}},
                    {"type": "value", "options": {"Open": {"color": "red", "index": 0}}},
                    {"type": "value", "options": {"In Progress": {"color": "yellow", "index": 1}}},
                    {"type": "value", "options": {"Scheduled": {"color": "blue", "index": 2}}},
                ],
            },
            {"id": "custom.cellOptions", "value": {"type": "color-text"}},
        ],
    }


def named_metric_queries(items: list[tuple[str, str]]) -> list[dict]:
    """One csv_metric_values query per label — works well with bargauge/stat rows."""
    refs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return [
        td_query(refs[i], "csv_metric_values", alias=alias, stringInput=value)
        for i, (alias, value) in enumerate(items)
    ]


def bargauge_panel(
    pid: int,
    title: str,
    queries: list[dict],
    *,
    desc: str = "",
    unit: str = "percent",
    max_val: float = 100,
    steps: list[dict] | None = None,
    orientation: str = "horizontal",
) -> dict:
    thresh = steps or [
        {"color": "green", "value": None},
        {"color": "yellow", "value": 70},
        {"color": "red", "value": 85},
    ]
    defaults: dict = {
        "color": {"mode": "thresholds"},
        "thresholds": {"mode": "absolute", "steps": thresh},
    }
    if unit:
        defaults["unit"] = unit
    if max_val:
        defaults["max"] = max_val
        defaults["min"] = 0
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": desc,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": queries, "queryOptions": {}, "transformations": []},
            },
            "vizConfig": {
                "group": "bargauge",
                "kind": "VizConfig",
                "version": VIZ_VER,
                "spec": {
                    "fieldConfig": {"defaults": defaults, "overrides": []},
                    "options": {
                        "displayMode": "gradient",
                        "legend": {
                            "calcs": [],
                            "displayMode": "list",
                            "placement": "bottom",
                            "showLegend": False,
                        },
                        "maxVizHeight": 300,
                        "minVizHeight": 16,
                        "orientation": orientation,
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                        "showUnfilled": True,
                        "sizing": "auto",
                        "valueMode": "color",
                    },
                },
            },
        },
    }


def timeseries_panel(
    pid: int,
    title: str,
    series_names: list[str],
    *,
    desc: str = "",
    unit: str = "Mbits",
) -> dict:
    queries = [
        td_query(f"{i}", "random_walk", alias=name, seriesCount=1)
        for i, name in enumerate(series_names)
    ]
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": desc,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": queries, "queryOptions": {}, "transformations": []},
            },
            "vizConfig": {
                "group": "timeseries",
                "kind": "VizConfig",
                "version": VIZ_VER,
                "spec": {
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "palette-classic"},
                            "custom": {
                                "drawStyle": "line",
                                "fillOpacity": 12,
                                "gradientMode": "opacity",
                                "lineWidth": 2,
                                "showPoints": "never",
                                "spanNulls": True,
                            },
                            "unit": unit,
                        },
                        "overrides": [],
                    },
                    "options": {
                        "legend": {
                            "calcs": ["mean", "max"],
                            "displayMode": "table",
                            "placement": "bottom",
                            "showLegend": True,
                        },
                        "tooltip": {"mode": "multi", "sort": "desc"},
                    },
                },
            },
        },
    }


def load_sankey_panel() -> dict:
    """Original Top Flow Conversations sankey (rich ktranslate example CSV)."""
    return json.loads(SANKEY_FIXTURE.read_text(encoding="utf-8"))


def build_elements(existing: dict) -> dict:
    _ = existing
    cmdb = [
        {"hostname": "core-sw-01", "role": "Core", "model": "N9K-9508", "site": "dc-east-1", "tier": "0", "status": "up"},
        {"hostname": "core-sw-02", "role": "Core", "model": "N9K-9508", "site": "dc-west-2", "tier": "0", "status": "up"},
        {"hostname": "dist-sw-11", "role": "Distribution", "model": "N9K-9364C", "site": "dc-east-1", "tier": "1", "status": "up"},
        {"hostname": "dist-sw-12", "role": "Distribution", "model": "N9K-9364C", "site": "dc-east-1", "tier": "1", "status": "degraded"},
        {"hostname": "dist-sw-21", "role": "Distribution", "model": "N9K-9364C", "site": "dc-west-2", "tier": "1", "status": "up"},
        {"hostname": "dist-sw-22", "role": "Distribution", "model": "N9K-9364C", "site": "dc-west-2", "tier": "1", "status": "up"},
        {"hostname": "access-sw-101", "role": "Access", "model": "C9300-48U", "site": "campus-north", "tier": "2", "status": "up"},
        {"hostname": "access-sw-102", "role": "Access", "model": "C9300-48U", "site": "campus-north", "tier": "2", "status": "up"},
        {"hostname": "tor-sw-301", "role": "ToR", "model": "SN4600C", "site": "edge-pop-01", "tier": "1", "status": "up"},
        {"hostname": "tor-sw-302", "role": "ToR", "model": "SN4600C", "site": "edge-pop-01", "tier": "1", "status": "up"},
        {"hostname": "rtr-core-01", "role": "Core router", "model": "MX204", "site": "dc-east-1", "tier": "0", "status": "up"},
        {"hostname": "rtr-core-02", "role": "Core router", "model": "MX204", "site": "dc-west-2", "tier": "0", "status": "up"},
        {"hostname": "rtr-edge-01", "role": "Edge router", "model": "ASR1001-X", "site": "edge-pop-01", "tier": "0", "status": "up"},
        {"hostname": "rtr-edge-02", "role": "Edge router", "model": "ASR1001-X", "site": "edge-pop-02", "tier": "0", "status": "up"},
    ]
    bgp_attention = [
        {"device": "access-sw-101", "peer": "10.64.12.1", "peer_device": "dist-sw-11", "state": "active", "prefixes": "0"},
        {"device": "rtr-edge-02", "peer": "203.0.113.42", "peer_device": "ISP-B", "state": "idle", "prefixes": "0"},
    ]
    offline_if = [
        {"device": "dist-sw-12", "interface": "Ethernet1/48", "admin": "down", "oper": "down", "note": "maintenance hold"},
        {"device": "access-sw-102", "interface": "Gi1/0/24", "admin": "up", "oper": "down", "note": "endpoint disconnected"},
    ]
    iface_errors = [
        {"device": "dist-sw-12", "interface": "Ethernet1/1", "errors_min": "186", "util_pct": "71"},
        {"device": "tor-sw-301", "interface": "swp1s0", "errors_min": "42", "util_pct": "58"},
    ]
    alerts = [
        {"alert": "BGP session not established", "severity": "Critical", "device": "access-sw-101", "since": "8m"},
        {"alert": "Interface error rate high", "severity": "High", "device": "dist-sw-12", "since": "12m"},
        {"alert": "CPU sustained above threshold", "severity": "Warning", "device": "dist-sw-12", "since": "22m"},
        {"alert": "Optics power low", "severity": "Medium", "device": "tor-sw-302", "since": "45m"},
    ]
    incidents = [
        {"number": "INC1048123", "priority": "2", "short_description": "East-west latency spike on payment VLAN", "cmdb_ci": "dist-sw-12", "state": "In Progress"},
        {"number": "INC1048099", "priority": "3", "short_description": "Intermittent packet loss on WAN edge", "cmdb_ci": "rtr-edge-01", "state": "Open"},
        {"number": "INC1048071", "priority": "4", "short_description": "SNMP collection gaps on access layer", "cmdb_ci": "access-sw-101", "state": "Open"},
    ]
    changes = [
        {"number": "CHG1021844", "type": "Normal", "short_description": "OS upgrade — distribution pair dc-east-1", "cmdb_ci": "dist-sw-11", "state": "Scheduled"},
        {"number": "CHG1021830", "type": "Standard", "short_description": "ACL rollout — edge routers", "cmdb_ci": "rtr-edge-01", "state": "Closed"},
    ]
    error_logs = [
        {"severity": "error", "device": "dist-sw-12", "facility": "IFMGR", "message": "Ethernet1/1 input errors threshold exceeded"},
        {"severity": "warning", "device": "access-sw-101", "facility": "BGP", "message": "Neighbor 10.64.12.1 state changed to Active"},
        {"severity": "notice", "device": "core-sw-01", "facility": "LLDP", "message": "New neighbor dist-sw-11 on Ethernet1/36"},
        {"severity": "warning", "device": "rtr-edge-01", "facility": "BGP", "message": "Prefix limit at 92% on peer ISP-A"},
    ]
    elements: dict = {}
    elements["panel-14"] = stat_panel(
        14,
        "Signal health by category",
        named_metric_queries([
            ("Switching", "97.5"),
            ("Routing", "94.0"),
            ("Firewalls", "100"),
            ("Load Balancers", "100"),
            ("Wireless", "91.0"),
            ("Critical Uplinks", "96.5"),
        ]),
        desc="Composite health score per network domain (demo).",
        links=[{"targetBlank": True, "title": "Device Summary", "url": "/d/ktranslate-device-summary/03-network-device-summary"}],
        thresholds=[{"color": "red", "value": None}, {"color": "yellow", "value": 90}, {"color": "green", "value": 95}],
    )
    elements["panel-21"] = stat_panel(
        21, "Active network alerts",
        [td_query("A", "csv_metric_values", alias="Alerts", stringInput="4")],
        color_mode="value", text_mode="value_and_name",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 3}, {"color": "red", "value": 5}],
    )
    elements["panel-22"] = stat_panel(
        22, "Open ITSM incidents",
        [td_query("A", "csv_metric_values", alias="Incidents", stringInput="3")],
        color_mode="value", text_mode="value_and_name",
    )
    elements["panel-23"] = stat_panel(
        23, "Offline devices",
        [td_query("A", "csv_metric_values", alias="Devices", stringInput="0")],
        color_mode="value", text_mode="value_and_name",
        thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
    )
    elements["panel-24"] = stat_panel(
        24, "Offline interfaces",
        [td_query("A", "csv_metric_values", alias="Interfaces", stringInput="2")],
        color_mode="value", text_mode="value_and_name",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 1}, {"color": "red", "value": 3}],
    )
    elements["panel-16"] = stat_panel(
        16, "WAN inbound Mbps",
        [td_query("A", "csv_metric_values", alias="Mbps", stringInput="8420")],
        color_mode="value", text_mode="value_and_name", unit="Mbits",
    )
    elements["panel-17"] = stat_panel(
        17, "WAN outbound Mbps",
        [td_query("A", "csv_metric_values", alias="Mbps", stringInput="7910")],
        color_mode="value", text_mode="value_and_name", unit="Mbits",
    )
    elements["panel-18"] = stat_panel(
        18, "Fabric errors / min",
        [td_query("A", "csv_metric_values", alias="Errors", stringInput="228")],
        color_mode="value", text_mode="value_and_name",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 100}, {"color": "red", "value": 200}],
    )
    elements["panel-19"] = stat_panel(
        19, "Sites reporting",
        [td_query("A", "csv_metric_values", alias="Sites", stringInput="4/4")],
        color_mode="value", text_mode="value_and_name",
    )
    elements["panel-15"] = deepcopy(load_sankey_panel())
    elements["panel-30"] = stat_panel(
        30, "Firewall health",
        [td_query("A", "csv_metric_values", alias="Health %", stringInput="100")],
        color_mode="background", text_mode="value_and_name",
    )
    elements["panel-31"] = bargauge_panel(
        31, "Edge throughput by site (Gbps)",
        named_metric_queries([("dc-east-1", "18"), ("dc-west-2", "14"), ("edge-pop-01", "9")]),
        unit="Gbits", max_val=20,
        steps=[{"color": "blue", "value": None}, {"color": "green", "value": 8}, {"color": "yellow", "value": 15}],
    )
    elements["panel-32"] = stat_panel(
        32, "VIP pool health",
        [td_query("A", "csv_metric_values", alias="Healthy", stringInput="98.5%")],
        color_mode="background", text_mode="value_and_name",
    )
    elements["panel-33"] = bargauge_panel(
        33, "VIP request rate (req/s)",
        named_metric_queries([("api-primary", "12400"), ("api-secondary", "8200"), ("portal", "3100"), ("auth", "2800")]),
        unit="reqps", max_val=15000,
        steps=[{"color": "green", "value": None}, {"color": "yellow", "value": 10000}, {"color": "red", "value": 13000}],
    )
    elements["panel-34"] = stat_panel(
        34, "BGP peers established",
        [td_query("A", "csv_metric_values", alias="Peers", stringInput="128")],
        color_mode="value", text_mode="value_and_name",
    )
    elements["panel-35"] = stat_panel(
        35, "BGP peers degraded",
        [td_query("A", "csv_metric_values", alias="Peers", stringInput="2")],
        color_mode="value", text_mode="value_and_name",
        thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
    )
    elements["panel-54"] = bargauge_panel(
        54, "BGP session state mix",
        named_metric_queries([("established", "126"), ("active", "1"), ("idle", "1"), ("connect", "0")]),
        unit="short", max_val=130,
        steps=[{"color": "green", "value": None}, {"color": "yellow", "value": 3}, {"color": "red", "value": 5}],
    )
    elements["panel-55"] = bargauge_panel(
        55, "Top peers by prefix count (K)",
        named_metric_queries([("ISP-A", "892"), ("rtr-core-02", "184"), ("rtr-edge-01", "92"), ("dist-sw-11", "2.4"), ("dist-sw-21", "2.3")]),
        unit="short", max_val=900, steps=[{"color": "blue", "value": None}],
    )
    elements["panel-56"] = timeseries_panel(
        56, "BGP state transitions / hr",
        ["rtr-core-01", "rtr-edge-01", "dist-sw-12"],
        desc="Demo trend — live: gnmi/kentik BGP flap counters.", unit="short",
    )
    elements["panel-36"] = table_panel(
        36, "BGP sessions needing attention",
        csv_content_query("A", bgp_attention, ["device", "peer", "peer_device", "state", "prefixes"]),
        overrides=[status_override("state")],
    )
    elements["panel-11"] = stat_panel(
        11, "Switching health",
        [td_query("A", "csv_metric_values", alias="On Prem Switching", stringInput="97.5")],
        links=[{"targetBlank": True, "title": "Device Summary", "url": "/d/ktranslate-device-summary/03-network-device-summary"}],
    )
    elements["panel-57"] = bargauge_panel(
        57, "Managed devices by site",
        named_metric_queries([("dc-east-1", "4"), ("dc-west-2", "4"), ("campus-north", "2"), ("edge-pop-01", "3")]),
        unit="short", max_val=5, steps=[{"color": "semi-dark-blue", "value": None}],
    )
    elements["panel-58"] = bargauge_panel(
        58, "Top CPU utilization",
        named_metric_queries([
            ("dist-sw-12", "78"), ("core-sw-01", "61"), ("tor-sw-301", "54"),
            ("dist-sw-21", "49"), ("access-sw-101", "44"), ("rtr-edge-01", "38"),
        ]),
    )
    elements["panel-59"] = bargauge_panel(
        59, "Top memory utilization",
        named_metric_queries([("dist-sw-12", "81"), ("core-sw-02", "67"), ("tor-sw-302", "59"), ("dist-sw-11", "52")]),
    )
    elements["panel-60"] = bargauge_panel(
        60, "Top interface utilization",
        named_metric_queries([
            ("core-sw-01 Et1/1", "82"), ("dist-sw-12 Et1/1", "71"),
            ("rtr-core-01 xe-0/0/0", "68"), ("tor-sw-301 swp8", "61"),
        ]),
    )
    elements["panel-61"] = timeseries_panel(
        61, "Fabric throughput (Mbps)",
        ["dc-east-1 inbound", "dc-east-1 outbound", "dc-west-2 inbound"],
        unit="Mbits",
    )
    elements["panel-40"] = table_panel(
        40, "CMDB inventory (sample)",
        csv_content_query("A", cmdb, ["hostname", "role", "model", "site", "tier", "status"]),
        overrides=[status_override("status")],
    )
    elements["panel-43"] = table_panel(
        43, "Offline interfaces",
        csv_content_query("A", offline_if, ["device", "interface", "admin", "oper", "note"]),
        overrides=[status_override("oper")],
    )
    elements["panel-45"] = table_panel(
        45, "Interfaces with elevated errors",
        csv_content_query("A", iface_errors, ["device", "interface", "errors_min", "util_pct"]),
        sort_col="errors_min",
    )
    elements["panel-47"] = stat_panel(
        47, "APs online",
        [td_query("A", "csv_metric_values", alias="APs", stringInput="214/218")],
        color_mode="background", text_mode="value_and_name",
    )
    elements["panel-48"] = bargauge_panel(
        48, "Clients by site",
        named_metric_queries([("campus-north", "1240"), ("dc-east-1", "680"), ("dc-west-2", "520")]),
        unit="short", max_val=1500, steps=[{"color": "purple", "value": None}],
    )
    elements["panel-62"] = bargauge_panel(
        62, "Alerts by severity",
        named_metric_queries([("Critical", "1"), ("High", "1"), ("Warning", "1"), ("Medium", "1")]),
        unit="short", max_val=5,
        steps=[{"color": "green", "value": None}, {"color": "yellow", "value": 2}, {"color": "red", "value": 3}],
    )
    elements["panel-50"] = table_panel(
        50, "Top active alerts",
        csv_content_query("A", alerts, ["alert", "severity", "device", "since"]),
        overrides=[severity_override("severity")],
    )
    elements["panel-51"] = table_panel(
        51, "Open incidents",
        csv_content_query("A", incidents, ["number", "priority", "short_description", "cmdb_ci", "state"]),
        overrides=[status_override("state")],
    )
    elements["panel-52"] = table_panel(
        52, "Recent changes",
        csv_content_query("A", changes, ["number", "type", "short_description", "cmdb_ci", "state"]),
        overrides=[status_override("state")],
    )
    elements["panel-53"] = table_panel(
        53, "Recent network logs",
        csv_content_query("A", error_logs, ["severity", "device", "facility", "message"]),
        overrides=[severity_override("severity")],
    )
    elements["panel-13"] = text_panel(
        13,
        "About this dashboard",
        f"""### Demo data — anonymous production shape

Synthetic **testdata** panels illustrate a multi-site fabric with CMDB enrichment and ITSM hooks. No customer-specific hostnames are used.

| Style | Role |
|-------|------|
| Stat / bar gauge | Health scores, capacity, top-N |
| Time series | Throughput and BGP churn trends |
| Tables | Exception queues only |
| Sankey | Rich flow conversation sample |

_Rebuilt {NOW} UTC_""",
    )
    return elements


def build_layout() -> dict:
    return {
        "kind": "RowsLayout",
        "spec": {
            "rows": [
                row_layout("Overview", [
                    grid_item("panel-14", 0, 0, 24, 4),
                    grid_item("panel-21", 0, 4, 6, 4),
                    grid_item("panel-22", 6, 4, 6, 4),
                    grid_item("panel-23", 12, 4, 6, 4),
                    grid_item("panel-24", 18, 4, 6, 4),
                    grid_item("panel-16", 0, 8, 6, 4),
                    grid_item("panel-17", 6, 8, 6, 4),
                    grid_item("panel-18", 12, 8, 6, 4),
                    grid_item("panel-19", 18, 8, 6, 4),
                    grid_item("panel-15", 0, 12, 24, 10),
                ]),
                row_layout("Firewalls", [
                    grid_item("panel-30", 0, 0, 6, 4),
                    grid_item("panel-31", 6, 0, 18, 7),
                ]),
                row_layout("Load Balancers", [
                    grid_item("panel-32", 0, 0, 6, 4),
                    grid_item("panel-33", 6, 0, 18, 7),
                ]),
                row_layout("Routing", [
                    grid_item("panel-34", 0, 0, 4, 4),
                    grid_item("panel-35", 4, 0, 4, 4),
                    grid_item("panel-54", 8, 0, 8, 7),
                    grid_item("panel-55", 16, 0, 8, 7),
                    grid_item("panel-56", 0, 7, 12, 7),
                    grid_item("panel-36", 12, 7, 12, 7),
                ]),
                row_layout("Switching", [
                    grid_item("panel-11", 0, 0, 4, 4),
                    grid_item("panel-57", 4, 0, 8, 7),
                    grid_item("panel-58", 12, 0, 6, 7),
                    grid_item("panel-59", 18, 0, 6, 7),
                    grid_item("panel-60", 0, 7, 12, 7),
                    grid_item("panel-61", 12, 7, 12, 7),
                    grid_item("panel-40", 0, 14, 14, 8),
                    grid_item("panel-43", 14, 14, 5, 8),
                    grid_item("panel-45", 19, 14, 5, 8),
                ]),
                row_layout("Wireless", [
                    grid_item("panel-47", 0, 0, 6, 4),
                    grid_item("panel-48", 6, 0, 12, 7),
                ]),
                row_layout("ITSM & operations", [
                    grid_item("panel-62", 0, 0, 8, 7),
                    grid_item("panel-50", 8, 0, 8, 7),
                    grid_item("panel-51", 16, 0, 8, 7),
                    grid_item("panel-52", 0, 7, 12, 6),
                    grid_item("panel-53", 12, 7, 12, 6),
                    grid_item("panel-13", 0, 13, 24, 5),
                ]),
            ]
        },
    }


def main() -> None:
    dash = gcx_get()
    dash["spec"]["elements"] = build_elements(dash["spec"]["elements"])
    dash["spec"]["layout"] = build_layout()
    dash["spec"]["title"] = "Network Summary"
    dash["spec"]["description"] = (
        "Executive network health — anonymous demo data with production-scale topology."
    )
    ann = dash.setdefault("metadata", {}).setdefault("annotations", {})
    ann["grafana.app/message"] = "Anonymous production demo + bargauge/timeseries styling"
    gcx_update(dash)
    print(f"Updated https://marcnetterfield1.grafana.net/d/{UID}/network-summary")


if __name__ == "__main__":
    main()
