#!/usr/bin/env python3
"""Expand ktranslate-device-summary with operator-focused tabs (v2 TabsLayout-safe).

Reorganizes the single Overview tab into:
  Overview | Traffic | Resources | Interfaces | Routing | Hardware | Events

**Agent rule:** When changing hardcoded queries in `build_new_panels()`, read [`docs/grafana-network-dashboard-design-patterns.md`](../../docs/grafana-network-dashboard-design-patterns.md) and align with [`local/docs/dashboard-query-lessons.md`](dashboard-query-lessons.md). Diff after edits: `python3 local/scripts/_compare-dashboard-live.py`.

Usage:
  python3 local/scripts/patch-device-summary-tabs.py --dry-run
  python3 local/scripts/patch-device-summary-tabs.py
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
OUT = ROOT / ".dash-payloads" / "ktranslate-device-summary-tabs-patched.json"
UID = "ktranslate-device-summary"
NS = "stacks-1061129"
VIZ_VER = "13.2.0-29854286369"
DS = "grafanacloud-prom"
LOKI = "grafanacloud-logs"
DETAIL_UID = "ktranslate-device-details"
SEL = 'provider=~"$provider",device_name=~"$device_name"'
WAN_IF = 'if_Alias=~".*WAN.*"'
NOTE = (
    "Fleet tabs + inventory stats, CHF collectors, traps, WAN ifAlias traffic; "
    "memory from ktranslate MemoryUtilization (MemoryUsed/MemoryFree tags); compact BGP/HW tables; "
    "fan/PSU sensors; fleet breakdown; Grafana network alerts (ALERTS)."
)

SNMP_TABLE_JUNK = frozenset(
    {
        "Time",
        "Value",
        "__name__",
        "Index",
        "eventType",
        "instrumentation_name",
        "job",
        "mib_name",
        "mib_table",
        "objectIdentifier",
        "provider",
        "service_name",
        "src_addr",
        "tags_container_service",
        "tags_kentik_model",
        "local_as",
        "hw_serial",
        "tBgpPeerNgOperStatus",
    }
)


def mem_pct_expr(sel: str = SEL) -> str:
    return f"kentik_snmp_MemoryUtilization{{{sel}}}"

# Existing panels (moved between tabs)
P_FLEET_STATS = ["panel-34", "panel-35", "panel-36", "panel-37", "panel-38", "panel-39", "panel-40", "panel-41"]
P_DEVICE_TABLE = "panel-16"
P_CPU = ["panel-23", "panel-24"]
P_TRAFFIC = ["panel-33", "panel-141", "panel-140"]
P_IFACE_HEALTH = ["panel-21", "panel-22"]


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


def prom_query(
    expr: str,
    *,
    instant: bool = True,
    legend: str = "",
    table: bool = False,
    ref_id: str = "A",
) -> dict[str, Any]:
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
            "hidden": False,
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": {"name": DS},
                "spec": spec,
            },
            "refId": ref_id,
        },
    }


def loki_query(expr: str) -> dict[str, Any]:
    return {
        "kind": "PanelQuery",
        "spec": {
            "hidden": False,
            "query": {
                "kind": "DataQuery",
                "group": "loki",
                "version": "v0",
                "datasource": {"name": LOKI},
                "spec": {"expr": expr, "queryType": "range"},
            },
            "refId": "A",
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
            "fillScreen": False,
            "hideHeader": False,
            "layout": {"kind": "GridLayout", "spec": {"items": items}},
        },
    }


def rows_layout(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "RowsLayout", "spec": {"rows": rows}}


def tab(title: str, layout: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "TabsLayoutTab", "spec": {"title": title, "layout": layout}}


def stat_viz(*, unit: str = "", thresholds: list[dict] | None = None) -> dict[str, Any]:
    steps = thresholds or [
        {"color": "green", "value": None},
        {"color": "yellow", "value": 1},
        {"color": "red", "value": 5},
    ]
    defaults: dict[str, Any] = {
        "color": {"mode": "thresholds"},
        "thresholds": {"mode": "absolute", "steps": steps},
    }
    if unit:
        defaults["unit"] = unit
    return {
        "kind": "VizConfig",
        "group": "stat",
        "version": VIZ_VER,
        "spec": {
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {
                "colorMode": "background",
                "graphMode": "none",
                "justifyMode": "auto",
                "orientation": "auto",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "textMode": "auto",
                "wideLayout": True,
            },
        },
    }


def pie_viz() -> dict[str, Any]:
    return {
        "kind": "VizConfig",
        "group": "piechart",
        "version": VIZ_VER,
        "spec": {
            "options": {
                "legend": {
                    "displayMode": "list",
                    "placement": "right",
                    "showLegend": True,
                    "values": ["value"],
                },
                "pieType": "pie",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                "sort": "desc",
                "tooltip": {"mode": "single"},
            },
            "fieldConfig": {
                "defaults": {"color": {"mode": "palette-classic"}, "unit": "short"},
                "overrides": [],
            },
        },
    }


def loki_metric_queries(trap_types: list[str]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for i, trap in enumerate(trap_types):
        queries.append(
            {
                "kind": "PanelQuery",
                "spec": {
                    "hidden": False,
                    "refId": chr(ord("A") + i),
                    "query": {
                        "kind": "DataQuery",
                        "group": "loki",
                        "version": "v0",
                        "datasource": {"name": LOKI},
                        "spec": {
                            "expr": (
                                f'sum(count_over_time({{service_name=~"ktranslate.*"}} '
                                f'|= "{trap}" [$__range]))'
                            ),
                            "queryType": "instant",
                            "instant": True,
                        },
                    },
                },
            }
        )
    return queries


def bargauge_viz(*, unit: str = "percent", horizontal: bool = True) -> dict[str, Any]:
    return {
        "kind": "VizConfig",
        "group": "bargauge",
        "version": VIZ_VER,
        "spec": {
            "fieldConfig": {
                "defaults": {
                    "color": {"mode": "thresholds"},
                    "max": 100 if unit == "percent" else None,
                    "min": 0,
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": 0},
                            {"color": "yellow", "value": 50},
                            {"color": "red", "value": 80},
                        ],
                    },
                    "unit": unit,
                },
                "overrides": [],
            },
            "options": {
                "displayMode": "gradient",
                "orientation": "horizontal" if horizontal else "vertical",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "showUnfilled": True,
            },
        },
    }


def timeseries_viz(*, unit: str = "short", stack: bool = False) -> dict[str, Any]:
    custom: dict[str, Any] = {
        "drawStyle": "line",
        "fillOpacity": 10 if not stack else 80,
        "lineWidth": 1,
        "showPoints": "never",
    }
    if stack:
        custom["stacking"] = {"group": "A", "mode": "normal"}
        custom["drawStyle"] = "bars"
        custom["fillOpacity"] = 80
    return {
        "kind": "VizConfig",
        "group": "timeseries",
        "version": VIZ_VER,
        "spec": {
            "options": {
                "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
                "tooltip": {"hideZeros": False, "mode": "multi", "sort": "desc"},
            },
            "fieldConfig": {
                "defaults": {
                    "color": {"mode": "palette-classic"},
                    "unit": unit,
                    "custom": custom,
                },
                "overrides": [],
            },
        },
    }


def table_viz(sort_field: str, *, unit: str = "none") -> dict[str, Any]:
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
                    "unit": unit,
                    "color": {"mode": "thresholds"},
                    "custom": {
                        "align": "auto",
                        "cellOptions": {"type": "auto"},
                        "footer": {"reducers": []},
                        "inspect": False,
                    },
                },
                "overrides": [],
            },
        },
    }


def logs_viz() -> dict[str, Any]:
    return {
        "kind": "VizConfig",
        "group": "logs",
        "version": VIZ_VER,
        "spec": {
            "options": {
                "dedupStrategy": "none",
                "enableLogDetails": True,
                "prettifyLogMessage": False,
                "showCommonLabels": False,
                "showLabels": False,
                "showTime": True,
                "sortOrder": "Descending",
                "wrapLogMessage": False,
            },
        },
    }


def make_panel(
    panel_id: int,
    title: str,
    description: str,
    queries: list[dict[str, Any]],
    viz: dict[str, Any],
    *,
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
                    "queries": queries,
                    "transformations": transformations or [],
                    "queryOptions": {},
                },
            },
            "vizConfig": viz,
        },
    }


def iface_util_table_transforms() -> list[dict[str, Any]]:
    return [
        {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
        {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
        {
            "kind": "Transformation",
            "group": "organize",
            "spec": {
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "device_name": 0,
                        "if_interface_name": 1,
                        "Value": 2,
                    },
                    "renameByName": {
                        "Value": "bps",
                        "device_name": "Device",
                        "if_interface_name": "Interface",
                    },
                }
            },
        },
        {
            "kind": "Transformation",
            "group": "sortBy",
            "spec": {"options": {"sort": [{"desc": True, "field": "bps"}]}},
        },
    ]


def fleet_table_transforms(
    columns: list[tuple[str, str]],
    *,
    sort_field: str | None = None,
    sort_desc: bool = True,
) -> list[dict[str, Any]]:
    keep = {src for src, _ in columns}
    exclude = {name: True for name in SNMP_TABLE_JUNK if name not in keep}
    rename = {src: dst for src, dst in columns if src != dst}
    transforms: list[dict[str, Any]] = [
        {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
        {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
        {
            "kind": "Transformation",
            "group": "organize",
            "spec": {
                "options": {
                    "excludeByName": exclude,
                    "indexByName": {src: idx for idx, (src, _) in enumerate(columns)},
                    "renameByName": rename,
                }
            },
        },
    ]
    if sort_field:
        transforms.append(
            {
                "kind": "Transformation",
                "group": "sortBy",
                "spec": {"options": {"sort": [{"desc": sort_desc, "field": sort_field}]}},
            }
        )
    return transforms


def hw_table_transforms() -> list[dict[str, Any]]:
    return fleet_table_transforms(
        [
            ("device_name", "Device"),
            ("hw_name", "Component"),
            ("hw_class", "Class"),
            ("tmnxHwOperState", "State"),
        ],
        sort_field="State",
        sort_desc=False,
    )


def bgp_table_transforms() -> list[dict[str, Any]]:
    return fleet_table_transforms(
        [
            ("device_name", "Device"),
            ("peer_group", "Peer Group"),
            ("peer_as", "Peer AS"),
            ("tBgpPeerNgConnState", "State"),
        ],
        sort_field="State",
        sort_desc=False,
    )


def fan_table_transforms() -> list[dict[str, Any]]:
    return fleet_table_transforms(
        [
            ("device_name", "Device"),
            ("Index", "Fan"),
            ("tmnxPhysChassisFanOperStatus", "State"),
        ],
        sort_field="State",
        sort_desc=False,
    )


def psu_table_transforms() -> list[dict[str, Any]]:
    return fleet_table_transforms(
        [
            ("device_name", "Device"),
            ("Index", "PSU"),
            ("tmnxPhysChassisPMOutputStatus", "State"),
        ],
        sort_field="State",
        sort_desc=False,
    )


def alert_table_transforms() -> list[dict[str, Any]]:
    return fleet_table_transforms(
        [
            ("alertname", "Alert"),
            ("severity", "Severity"),
            ("device_name", "Device"),
            ("domain", "Domain"),
            ("alertstate", "State"),
        ],
        sort_field="Severity",
        sort_desc=True,
    )


def iface_err_table_transforms() -> list[dict[str, Any]]:
    return [
        {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
        {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
        {
            "kind": "Transformation",
            "group": "organize",
            "spec": {
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "device_name": 0,
                        "if_interface_name": 1,
                        "Value": 2,
                    },
                    "renameByName": {
                        "Value": "Errors/s",
                        "device_name": "Device",
                        "if_interface_name": "Interface",
                    },
                }
            },
        },
        {
            "kind": "Transformation",
            "group": "sortBy",
            "spec": {"options": {"sort": [{"desc": True, "field": "Errors/s"}]}},
        },
    ]


def wan_table_transforms() -> list[dict[str, Any]]:
    return [
        {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
        {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
        {
            "kind": "Transformation",
            "group": "organize",
            "spec": {
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "device_name": 0,
                        "if_Alias": 1,
                        "if_Description": 2,
                        "Value": 3,
                    },
                    "renameByName": {
                        "Value": "bps",
                        "device_name": "Device",
                        "if_Alias": "Alias",
                        "if_Description": "Interface",
                    },
                }
            },
        },
        {
            "kind": "Transformation",
            "group": "sortBy",
            "spec": {"options": {"sort": [{"desc": True, "field": "bps"}]}},
        },
    ]


def build_new_panels() -> dict[str, dict[str, Any]]:
    f = SEL
    wan = f"{f},{WAN_IF}"
    mem = mem_pct_expr(f)
    panels: dict[str, dict[str, Any]] = {
        "panel-101": make_panel(
            101,
            "Unhealthy Pollers",
            "Devices where ktranslate PollingHealth is not Healthy (1).",
            [prom_query(f'count(kentik_snmp_PollingHealth{{{f}}} != 1) OR vector(0)')],
            stat_viz(unit="short"),
        ),
        "panel-102": make_panel(
            102,
            "SNMP Collectors",
            "Active ktranslate SNMP pollers (CHF heartbeat).",
            [
                prom_query(
                    'count(count by(service_name) ('
                    'kentik_ktranslate_chf_kkc_jchfq{service_name=~"ktranslate-snmp.*"})) OR vector(0)'
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-103": make_panel(
            103,
            "Flow Collectors",
            "Active ktranslate NetFlow/sFlow collectors.",
            [
                prom_query(
                    'count(count by(service_name) ('
                    'kentik_ktranslate_chf_kkc_jchfq{service_name=~"ktranslate-flow.*|ktranslate-sflow.*"})) '
                    "OR vector(0)"
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-104": make_panel(
            104,
            "Syslog Collectors",
            "Active ktranslate syslog collectors.",
            [
                prom_query(
                    'count(count by(service_name) ('
                    'kentik_ktranslate_chf_kkc_jchfq{service_name=~"ktranslate-syslog.*"})) OR vector(0)'
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-105": make_panel(
            105,
            "Memory by Device",
            "Memory % from ktranslate MemoryUtilization (MemoryUsed + MemoryFree tags).",
            [
                prom_query(
                    f"sort_desc(max by(device_name) ({mem}))",
                    legend="{{device_name}}",
                    instant=True,
                )
            ],
            bargauge_viz(unit="percent"),
        ),
        "panel-106": make_panel(
            106,
            "Memory Utilization — Top 10",
            "Memory % trend for hottest devices.",
            [
                prom_query(
                    f"topk(10, max by(device_name) ({mem}))",
                    legend="{{device_name}}",
                    instant=False,
                )
            ],
            timeseries_viz(unit="percent"),
        ),
        "panel-107": make_panel(
            107,
            "Top Interface Errors (fleet)",
            "Sum of in+out error counters per interface (delta gauge / 60s).",
            [
                prom_query(
                    "topk(20, sum by(device_name, if_interface_name) ("
                    f"(kentik_snmp_ifInErrors{{{f}}}) / 60 + "
                    f"(kentik_snmp_ifOutErrors{{{f}}}) / 60))",
                    table=True,
                )
            ],
            table_viz("Errors/s", unit="ops"),
            transformations=iface_err_table_transforms(),
        ),
        "panel-108": make_panel(
            108,
            "Top Interface Utilization (bps)",
            "Highest combined in+out throughput per interface.",
            [
                prom_query(
                    "topk(20, sum by(device_name, if_interface_name) ("
                    f"(kentik_snmp_ifHCInOctets{{{f}}}) * 8 / 60 + "
                    f"(kentik_snmp_ifHCOutOctets{{{f}}}) * 8 / 60))",
                    table=True,
                )
            ],
            table_viz("bps", unit="bps"),
            transformations=iface_util_table_transforms(),
        ),
        "panel-109": make_panel(
            109,
            "BGP Established % by Device",
            "Share of BGP peers in established state per device.",
            [
                prom_query(
                    "sort_desc(\n"
                    f"  100 * count by(device_name) (kentik_snmp_tBgpPeerNgConnState{{{f}}} == 6)\n"
                    f"  / count by(device_name) (kentik_snmp_tBgpPeerNgConnState{{{f}}})\n"
                    ")",
                    legend="{{device_name}}",
                    instant=True,
                )
            ],
            bargauge_viz(unit="percent"),
        ),
        "panel-110": make_panel(
            110,
            "BGP Peers Established",
            "Count of established BGP sessions fleet-wide.",
            [
                prom_query(
                    f'count(kentik_snmp_tBgpPeerNgConnState{{{f}}} == 6) OR vector(0)',
                )
            ],
            stat_viz(
                unit="short",
                thresholds=[
                    {"color": "red", "value": None},
                    {"color": "green", "value": 1},
                ],
            ),
        ),
        "panel-111": make_panel(
            111,
            "BGP Peers Total",
            "All BGP peers being polled.",
            [prom_query(f"count(kentik_snmp_tBgpPeerNgConnState{{{f}}}) OR vector(0)")],
            stat_viz(unit="short"),
        ),
        "panel-112": make_panel(
            112,
            "BGP Sessions Not Established",
            "Peers where ConnState is not established (string enum label).",
            [
                prom_query(
                    f"kentik_snmp_tBgpPeerNgConnState{{{f},tBgpPeerNgConnState!=\"established\"}}",
                    table=True,
                )
            ],
            table_viz("State", unit="none"),
            transformations=bgp_table_transforms(),
        ),
        "panel-113": make_panel(
            113,
            "BGP Flaps (range)",
            "Peer flap counter increase over dashboard time range.",
            [
                prom_query(
                    f"topk(10, sum by(device_name) ("
                    f"increase(kentik_snmp_tBgpPeerNgOperFlaps{{{f}}}[$__range])))",
                    legend="{{device_name}}",
                    instant=False,
                )
            ],
            timeseries_viz(unit="short"),
        ),
        "panel-114": make_panel(
            114,
            "Devices with Hardware Issues",
            "Count of devices with any chassis component not inService (2).",
            [
                prom_query(
                    f"count(count by(device_name) (kentik_snmp_tmnxHwOperState{{{f}}} != 2)) OR vector(0)"
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-115": make_panel(
            115,
            "Max Temperature by Device",
            "Highest chassis/sensor temperature (°C) per device.",
            [
                prom_query(
                    f"sort_desc(max by(device_name) (kentik_snmp_tmnxHwTemperature{{{f}}}))",
                    legend="{{device_name}}",
                    instant=True,
                )
            ],
            bargauge_viz(unit="celsius"),
        ),
        "panel-116": make_panel(
            116,
            "Temperature Over Time",
            "Chassis temperature trend (top 10 devices).",
            [
                prom_query(
                    f"topk(10, max by(device_name) (kentik_snmp_tmnxHwTemperature{{{f}}}))",
                    legend="{{device_name}}",
                    instant=False,
                )
            ],
            timeseries_viz(unit="celsius"),
        ),
        "panel-117": make_panel(
            117,
            "Non-inService Components",
            "Chassis FRUs in failed, outOfService, or diagnosing state (excludes empty slots).",
            [
                prom_query(
                    f"kentik_snmp_tmnxHwOperState{{{f},"
                    'tmnxHwOperState=~"failed|outOfService|diagnosing|resetPending|booting"}}',
                    table=True,
                )
            ],
            table_viz("State", unit="none"),
            transformations=hw_table_transforms(),
        ),
        "panel-118": make_panel(
            118,
            "Collectors by Type",
            "CHF heartbeat series grouped by ktranslate service_name prefix.",
            [
                prom_query(
                    'sum by (collector) (label_replace('
                    "count by (service_name) (kentik_ktranslate_chf_kkc_jchfq), "
                    '"collector", "$1", "service_name", "ktranslate-([^-]+).*"))',
                    legend="{{collector}}",
                    instant=True,
                )
            ],
            pie_viz(),
        ),
        "panel-119": make_panel(
            119,
            "Total Interfaces",
            "IF-MIB interfaces polled fleet-wide.",
            [prom_query(f"count(kentik_snmp_if_OperStatus{{{f}}}) OR vector(0)")],
            stat_viz(unit="short"),
        ),
        "panel-120": make_panel(
            120,
            "Admin-Up Interfaces",
            "Interfaces with ifAdminStatus != down.",
            [
                prom_query(
                    f'count(kentik_snmp_if_OperStatus{{{f},if_AdminStatus!="down"}}) OR vector(0)'
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-121": make_panel(
            121,
            "Oper-Up Interfaces",
            "Interfaces currently oper-up (ifOperStatus == 1).",
            [
                prom_query(
                    f'count(kentik_snmp_if_OperStatus{{{f}}} == 1) OR vector(0)'
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-122": make_panel(
            122,
            "SNMP Trap Rate",
            "ktranslate CHF snmp_traps counter (all SNMP collectors).",
            [
                prom_query(
                    'sum(rate(kentik_ktranslate_chf_kkc_snmp_traps{service_name=~"ktranslate-snmp.*"}[5m])) '
                    "OR vector(0)",
                    instant=False,
                )
            ],
            stat_viz(unit="ops"),
        ),
        "panel-123": make_panel(
            123,
            "Recent Network Syslog",
            "ktranslate syslog stream — link/BGP/fault keywords.",
            [
                loki_query(
                    '{service_name=~"ktranslate.*"} '
                    '|~ "(?i)(link|bgp|down|fail|error|flap|interface)"'
                )
            ],
            logs_viz(),
        ),
        "panel-124": make_panel(
            124,
            "Recent SNMP Traps",
            "ktranslate trap OTLP logs (KSnmpTrap + standard trap OIDs).",
            [
                loki_query(
                    '{service_name=~"ktranslate.*"} '
                    '|~ "(?i)(KSnmpTrap|linkDown|linkUp|coldStart|warmStart|authenticationFailure|trapdata)"'
                )
            ],
            logs_viz(),
        ),
        "panel-125": make_panel(
            125,
            "Trap Types (range)",
            "Count of trap-related log lines by trap keyword.",
            loki_metric_queries(
                ["linkDown", "linkUp", "coldStart", "warmStart", "authenticationFailure"]
            ),
            pie_viz(),
        ),
        "panel-126": make_panel(
            126,
            "Traps by Device (range)",
            "Trap log volume grouped by device_name (when present in OTLP).",
            [
                loki_query(
                    'sum by (device_name) (count_over_time('
                    '{service_name=~"ktranslate.*"} |= "KSnmpTrap" | json | device_name != "" '
                    "[$__range]))"
                )
            ],
            table_viz("Value", unit="short"),
        ),
        "panel-127": make_panel(
            127,
            "WAN Traffic by Interface",
            "Interfaces with ifAlias matching .*WAN.* (SRL interface description).",
            [
                prom_query(
                    f"topk(20, sum by(device_name, if_Alias, if_Description) ("
                    f"(kentik_snmp_ifHCInOctets{{{wan}}}) * 8 / 60 + "
                    f"(kentik_snmp_ifHCOutOctets{{{wan}}}) * 8 / 60))",
                    table=True,
                )
            ],
            table_viz("bps", unit="bps"),
            transformations=wan_table_transforms(),
        ),
        "panel-128": make_panel(
            128,
            "WAN Traffic Over Time",
            "Stacked bps on WAN-tagged interfaces.",
            [
                prom_query(
                    f"sum by(device_name, if_Description) ("
                    f"(kentik_snmp_ifHCInOctets{{{wan}}}) * 8 / 60 + "
                    f"(kentik_snmp_ifHCOutOctets{{{wan}}}) * 8 / 60)",
                    legend="{{device_name}} {{if_Description}}",
                    instant=False,
                )
            ],
            timeseries_viz(unit="bps", stack=True),
        ),
        "panel-129": make_panel(
            129,
            "Non-OK Fans",
            "Chassis fans not deviceStateInService (TIMETRA tmnxPhysChassisFan).",
            [
                prom_query(
                    f'count(kentik_snmp_tmnxPhysChassisFanOperStatus{{{f},'
                    'tmnxPhysChassisFanOperStatus!="deviceStateInService"}) OR vector(0)'
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-130": make_panel(
            130,
            "Non-OK Power Supplies",
            "PSUs in failed, outOfService, or degraded state.",
            [
                prom_query(
                    f'count(kentik_snmp_tmnxPhysChassisPMOutputStatus{{{f},'
                    'tmnxPhysChassisPMOutputStatus=~"failed|outOfService|degraded"}) OR vector(0)'
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-131": make_panel(
            131,
            "Fan Issues",
            "Fans not in service — Device, slot, oper status.",
            [
                prom_query(
                    f"kentik_snmp_tmnxPhysChassisFanOperStatus{{{f},"
                    'tmnxPhysChassisFanOperStatus!="deviceStateInService"}',
                    table=True,
                )
            ],
            table_viz("State", unit="none"),
            transformations=fan_table_transforms(),
        ),
        "panel-132": make_panel(
            132,
            "Power Supply Issues",
            "PSUs not online or not equipped.",
            [
                prom_query(
                    f"kentik_snmp_tmnxPhysChassisPMOutputStatus{{{f},"
                    'tmnxPhysChassisPMOutputStatus!~"online|notEquipped|unknown"}',
                    table=True,
                )
            ],
            table_viz("State", unit="none"),
            transformations=psu_table_transforms(),
        ),
        "panel-133": make_panel(
            133,
            "Devices by Provider",
            "Unique devices grouped by ktranslate SNMP profile provider label.",
            [
                prom_query(
                    f"count by (provider) (count by (device_name) (kentik_snmp_if_OperStatus{{{f}}}))",
                    legend="{{provider}}",
                    instant=True,
                )
            ],
            pie_viz(),
        ),
        "panel-134": make_panel(
            134,
            "Devices by Model",
            "Unique devices grouped by tags_kentik_model (platform category).",
            [
                prom_query(
                    "count by (tags_kentik_model) "
                    f"(count by (device_name) (kentik_snmp_if_OperStatus{{{f}}}))",
                    legend="{{tags_kentik_model}}",
                    instant=True,
                )
            ],
            pie_viz(),
        ),
        "panel-135": make_panel(
            135,
            "Devices by Poller",
            "Unique devices grouped by ktranslate service_name (SNMP collector).",
            [
                prom_query(
                    f"count by (service_name) (count by (device_name) (kentik_snmp_if_OperStatus{{{f}}}))",
                    legend="{{service_name}}",
                    instant=True,
                )
            ],
            pie_viz(),
        ),
        "panel-136": make_panel(
            136,
            "Syslog Volume",
            "ktranslate CHF syslog_messages rate across syslog collectors.",
            [
                prom_query(
                    'sum(rate(kentik_ktranslate_chf_kkc_syslog_messages{service_name=~"ktranslate-syslog.*"}[5m])) '
                    "OR vector(0)",
                    instant=False,
                )
            ],
            timeseries_viz(unit="ops"),
        ),
        "panel-137": make_panel(
            137,
            "SNMP Trap Volume",
            "ktranslate CHF snmp_traps rate across SNMP collectors.",
            [
                prom_query(
                    'sum(rate(kentik_ktranslate_chf_kkc_snmp_traps{service_name=~"ktranslate-snmp.*"}[5m])) '
                    "OR vector(0)",
                    instant=False,
                )
            ],
            timeseries_viz(unit="ops"),
        ),
        "panel-138": make_panel(
            138,
            "Firing Network Alerts",
            "Grafana-managed alerts with label category=network (provision-network-alerts.py).",
            [
                prom_query(
                    'count(ALERTS{alertstate="firing", category="network"}) OR vector(0)',
                )
            ],
            stat_viz(unit="short"),
        ),
        "panel-139": make_panel(
            139,
            "Active Network Alerts",
            "Firing alert instances from Network Lab / ktranslate rule group.",
            [
                prom_query(
                    'ALERTS{alertstate="firing", category="network"}',
                    table=True,
                )
            ],
            table_viz("Alert", unit="none"),
            transformations=alert_table_transforms(),
        ),
        "panel-141": make_panel(
            141,
            "Traffic In — Top 10 Devices (Stacked)",
            "Highest inbound bps per device (ktranslate delta gauge / 60s).",
            [
                prom_query(
                    f"topk(10, sum by(device_name) ("
                    f"(kentik_snmp_ifHCInOctets{{{f}}}) * 8 / 60))",
                    legend="{{device_name}}",
                    instant=False,
                )
            ],
            timeseries_viz(unit="bps", stack=True),
        ),
    }
    return panels


def fleet_overview_row() -> dict[str, Any]:
    items = []
    stats = [
        (0, 0, P_FLEET_STATS[0]),
        (6, 0, P_FLEET_STATS[1]),
        (12, 0, P_FLEET_STATS[2]),
        (18, 0, P_FLEET_STATS[3]),
        (0, 5, P_FLEET_STATS[4]),
        (6, 5, P_FLEET_STATS[5]),
        (12, 5, P_FLEET_STATS[6]),
        (18, 5, P_FLEET_STATS[7]),
    ]
    for x, y, name in stats:
        items.append(grid_item(x, y, 6, 5 if y == 0 else 4, name))
    items.append(grid_item(0, 9, 24, 12, P_DEVICE_TABLE))
    return layout_row("Fleet Overview", items)


def collection_row() -> dict[str, Any]:
    return layout_row(
        "Collection Health",
        [
            grid_item(0, 0, 6, 5, "panel-101"),
            grid_item(6, 0, 6, 5, "panel-102"),
            grid_item(12, 0, 6, 5, "panel-103"),
            grid_item(18, 0, 6, 5, "panel-104"),
            grid_item(0, 5, 12, 8, "panel-118"),
        ],
    )


def fleet_breakdown_row() -> dict[str, Any]:
    return layout_row(
        "Fleet Breakdown & Alerts",
        [
            grid_item(0, 0, 6, 5, "panel-138"),
            grid_item(6, 0, 6, 8, "panel-133"),
            grid_item(12, 0, 6, 8, "panel-134"),
            grid_item(18, 0, 6, 8, "panel-135"),
            grid_item(0, 5, 24, 10, "panel-139"),
        ],
    )


def inventory_row() -> dict[str, Any]:
    return layout_row(
        "Fleet Inventory",
        [
            grid_item(0, 0, 8, 5, "panel-119"),
            grid_item(8, 0, 8, 5, "panel-120"),
            grid_item(16, 0, 8, 5, "panel-121"),
        ],
    )


def build_tabs_layout() -> dict[str, Any]:
    return {
        "kind": "TabsLayout",
        "spec": {
            "tabs": [
                tab(
                    "Overview",
                    rows_layout(
                        [
                            fleet_overview_row(),
                            fleet_breakdown_row(),
                            inventory_row(),
                            collection_row(),
                        ]
                    ),
                ),
                tab(
                    "Traffic",
                    rows_layout(
                        [
                            layout_row(
                                "Fleet Traffic",
                                [
                                    grid_item(0, 0, 24, 12, P_TRAFFIC[0]),
                                    grid_item(0, 12, 12, 10, P_TRAFFIC[1]),
                                    grid_item(12, 12, 12, 10, P_TRAFFIC[2]),
                                ],
                            ),
                            layout_row(
                                "WAN Traffic (ifAlias ~ .*WAN.*)",
                                [
                                    grid_item(0, 0, 12, 10, "panel-128"),
                                    grid_item(12, 0, 12, 10, "panel-127"),
                                ],
                            ),
                        ]
                    ),
                ),
                tab(
                    "Resources",
                    rows_layout(
                        [
                            layout_row(
                                "CPU",
                                [
                                    grid_item(0, 0, 12, 8, P_CPU[0]),
                                    grid_item(12, 0, 12, 8, P_CPU[1]),
                                ],
                            ),
                            layout_row(
                                "Memory",
                                [
                                    grid_item(0, 0, 12, 8, "panel-105"),
                                    grid_item(12, 0, 12, 8, "panel-106"),
                                ],
                            ),
                        ]
                    ),
                ),
                tab(
                    "Interfaces",
                    rows_layout(
                        [
                            layout_row(
                                "Link State",
                                [
                                    grid_item(0, 0, 12, 8, P_IFACE_HEALTH[0]),
                                    grid_item(12, 0, 12, 8, P_IFACE_HEALTH[1]),
                                ],
                            ),
                            layout_row(
                                "Errors & Utilization",
                                [
                                    grid_item(0, 0, 12, 10, "panel-107"),
                                    grid_item(12, 0, 12, 10, "panel-108"),
                                ],
                            ),
                        ]
                    ),
                ),
                tab(
                    "Routing",
                    rows_layout(
                        [
                            layout_row(
                                "BGP Summary",
                                [
                                    grid_item(0, 0, 6, 5, "panel-110"),
                                    grid_item(6, 0, 6, 5, "panel-111"),
                                    grid_item(12, 0, 12, 8, "panel-109"),
                                ],
                            ),
                            layout_row(
                                "BGP Detail",
                                [
                                    grid_item(0, 0, 12, 10, "panel-112"),
                                    grid_item(12, 0, 12, 10, "panel-113"),
                                ],
                            ),
                        ]
                    ),
                ),
                tab(
                    "Hardware",
                    rows_layout(
                        [
                            layout_row(
                                "Chassis Health",
                                [
                                    grid_item(0, 0, 6, 5, "panel-114"),
                                    grid_item(6, 0, 6, 5, "panel-129"),
                                    grid_item(12, 0, 6, 5, "panel-130"),
                                    grid_item(18, 0, 6, 8, "panel-115"),
                                ],
                            ),
                            layout_row(
                                "Fans & Power",
                                [
                                    grid_item(0, 0, 12, 10, "panel-131"),
                                    grid_item(12, 0, 12, 10, "panel-132"),
                                ],
                            ),
                            layout_row(
                                "Temperature & Components",
                                [
                                    grid_item(0, 0, 24, 10, "panel-116"),
                                    grid_item(0, 10, 24, 10, "panel-117"),
                                ],
                            ),
                        ]
                    ),
                ),
                tab(
                    "Events",
                    rows_layout(
                        [
                            layout_row(
                                "Event Volume",
                                [
                                    grid_item(0, 0, 12, 8, "panel-136"),
                                    grid_item(12, 0, 12, 8, "panel-137"),
                                ],
                            ),
                            layout_row(
                                "Traps",
                                [
                                    grid_item(0, 0, 6, 5, "panel-122"),
                                    grid_item(6, 0, 9, 8, "panel-125"),
                                    grid_item(15, 0, 9, 8, "panel-126"),
                                ],
                            ),
                            layout_row(
                                "Syslog",
                                [grid_item(0, 0, 12, 12, "panel-123")],
                            ),
                            layout_row(
                                "Trap Log Stream",
                                [grid_item(0, 0, 24, 12, "panel-124")],
                            ),
                        ]
                    ),
                ),
            ]
        },
    }


def fix_device_detail_links(elements: dict[str, Any]) -> None:
    url = (
        f"/d/{DETAIL_UID}/04-network-device-details?"
        "var-instance=${__data.fields.device_name}&var-datasource=${datasource}"
        "&from=${__from}&to=${__to}"
    )
    legacy = "/d/magz6qw1?var-instance=${__data.fields.device_name}"
    for key, panel in elements.items():
        blob = json.dumps(panel)
        if "magz6qw1" not in blob:
            continue
        blob = blob.replace(legacy, url).replace("/d/magz6qw1", f"/d/{DETAIL_UID}/04-network-device-details")
        elements[key] = json.loads(blob)


def fix_memory_exprs(elements: dict[str, Any]) -> None:
    """Restore dashboards that were patched to manual Used/Available formula."""
    manual = (
        "100 * kentik_snmp_MemoryUsed / "
        "(kentik_snmp_MemoryUsed + kentik_snmp_MemoryAvailable)"
    )
    for key, panel in list(elements.items()):
        blob = json.dumps(panel)
        if manual not in blob:
            continue
        elements[key] = json.loads(blob.replace(manual, "kentik_snmp_MemoryUtilization"))


def collect_layout_panel_refs(layout: dict[str, Any]) -> set[str]:
    refs: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "ElementReference":
                refs.add(node["name"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(layout)
    return refs


def validate_layout_elements(elements: dict[str, Any], layout: dict[str, Any]) -> None:
    missing = sorted(collect_layout_panel_refs(layout) - set(elements))
    if missing:
        raise ValueError(
            "Layout references panels missing from elements: " + ", ".join(missing)
        )


def patch_dashboard(dash: dict) -> dict:
    out = copy.deepcopy(dash)
    spec = out.setdefault("spec", {})
    elements = spec.setdefault("elements", {})
    elements.update(build_new_panels())
    fix_device_detail_links(elements)
    fix_memory_exprs(elements)
    layout = build_tabs_layout()
    validate_layout_elements(elements, layout)
    spec["layout"] = layout
    desc = spec.get("description", "")
    if "Fleet tabs" not in desc:
        spec["description"] = (desc.rstrip() + "\n\n" + NOTE).strip()
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
    args = ap.parse_args()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    dash = get_dashboard(env)
    gen = dash.get("metadata", {}).get("generation", "?")
    layout = dash.get("spec", {}).get("layout", {}).get("kind")
    print(f"Fetched {UID} generation={gen} layout={layout}")

    patched = patch_dashboard(dash)
    OUT.write_text(json.dumps(patched, indent=2), encoding="utf-8")
    tabs = patched["spec"]["layout"]["spec"]["tabs"]
    print(f"Wrote {OUT} ({len(tabs)} tabs)")

    if args.dry_run:
        print("dry-run: not pushing")
        return 0

    put_dashboard(env, patched)
    print(f"Patched {env['GRAFANA_URL'].rstrip('/')}/d/{UID}")
    print(f"layout={patched['spec']['layout']['kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
