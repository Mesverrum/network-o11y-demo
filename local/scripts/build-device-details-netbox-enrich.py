#!/usr/bin/env python3
"""Clone ktranslate Device Details and enrich with NetBox SoT panels + deep links.

Creates folder ``netbox-enrichment`` and dashboard UID
``ktranslate-device-details-netbox`` (TabsLayout-safe v2 API).

Live dashboard 25 is Infinity-split (no netbox-inventory OTLP). This builder still
emits legacy PromQL SoT queries — it will refuse to overwrite live unless
``FORCE_DEVICE_DETAILS_NETBOX_BUILD=1``. Prefer
``split-device-details-netbox-panels.py`` + ``retarget-netbox-otlp-to-infinity.py``.

Usage:
  python local/scripts/build-device-details-netbox-enrich.py
  python local/scripts/build-device-details-netbox-enrich.py --dry-run
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "netbox-enrich"
NS = "stacks-1061129"
SRC_UID = "ktranslate-device-details"
DST_UID = "ktranslate-device-details-netbox"
FOLDER_UID = "netbox-enrichment"
FOLDER_TITLE = "NetBox × Device Details"
DEFAULT_NETBOX_URL = (
    "http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000"
)
NB_SEL = (
    'deployment_host="aws-colocated-lab",service_name="netbox-inventory",'
    'device_name=~"$instance"'
)
NB_ALL = 'deployment_host="aws-colocated-lab",service_name="netbox-inventory"'


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:4000]}
        return e.code, payload


def ensure_folder(env: dict[str, str]) -> None:
    code, _ = api(env, "GET", f"/api/folders/{FOLDER_UID}")
    if code == 200:
        print(f"folder exists: {FOLDER_UID}")
        return
    code, out = api(
        env,
        "POST",
        "/api/folders",
        {"uid": FOLDER_UID, "title": FOLDER_TITLE},
    )
    if code not in (200, 201, 409, 412):
        raise RuntimeError(f"create folder failed HTTP {code}: {out}")
    print(f"folder created: {FOLDER_UID} ({FOLDER_TITLE})")


def max_panel_id(elements: dict[str, Any]) -> int:
    mx = 0
    for el in elements.values():
        try:
            mx = max(mx, int((el.get("spec") or {}).get("id") or 0))
        except (TypeError, ValueError):
            pass
    for key in elements:
        m = re.search(r"(\d+)$", key)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def text_panel(pid: int, title: str, content: str, *, height_hint: int = 8) -> dict:
    _ = height_hint
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": "",
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": [], "transformations": [], "queryOptions": {}},
            },
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


def prom_query(expr: str, *, ref: str = "A", instant: bool = True, fmt: str = "", hidden: bool = False) -> dict:
    qspec: dict[str, Any] = {
        "editorMode": "code",
        "expr": expr,
        "legendFormat": "__auto",
        "queryType": "instant" if instant else "timeSeriesQuery",
        "range": not instant,
        "instant": instant,
    }
    if fmt:
        qspec["format"] = fmt
    return {
        "kind": "PanelQuery",
        "spec": {
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": {"name": "${datasource}"},
                "spec": qspec,
            },
            "refId": ref,
            "hidden": hidden,
        },
    }


def sql_expr_query(expression: str, *, ref: str = "B") -> dict:
    return {
        "kind": "PanelQuery",
        "spec": {
            "query": {
                "kind": "DataQuery",
                "group": "__expr__",
                "version": "v0",
                "datasource": {"name": "__expr__"},
                "spec": {
                    "expression": expression,
                    "type": "sql",
                },
            },
            "refId": ref,
            "hidden": False,
        },
    }


def field_details_table_viz() -> dict:
    return {
        "kind": "VizConfig",
        "group": "table",
        "version": "",
        "spec": {
            "options": {"cellHeight": "sm", "showHeader": True},
            "fieldConfig": {
                "defaults": {
                    "custom": {
                        "align": "auto",
                        "cellOptions": {"type": "auto"},
                        "inspect": False,
                        "wrapText": True,
                    }
                },
                "overrides": [
                    {
                        "matcher": {"id": "byName", "options": "Field"},
                        "properties": [{"id": "custom.width", "value": 140}],
                    },
                    {
                        "matcher": {"id": "byName", "options": "Details"},
                        "properties": [
                            {"id": "custom.wrapText", "value": True},
                            {
                                "id": "links",
                                "value": [
                                    {
                                        "title": "Open in NetBox (when Details is an ID)",
                                        "url": "${netbox_url}/dcim/devices/${__value.raw}/",
                                        "targetBlank": True,
                                    }
                                ],
                            },
                        ],
                    },
                ],
            },
        },
    }


def netbox_identity_panel(pid: int, *, selected: bool = True) -> dict:
    """CMDB identity via NetBox REST (Infinity) — Field/Details rows.

    Avoids Grafana SQL expressions (broken for this label set). Official NetBox
    plugin can replace Infinity later; keep the same Field/Details shape.
    """
    if not selected:
        expr = (
            "sum by (device_name, netbox_id, netbox_status, site, role, manufacturer, "
            "platform, primary_ip, serial, interface_count, tags) ("
            f"last_over_time(netbox_device_info{{{NB_ALL}}}[15m]))"
        )
        return netbox_fleet_table_panel(
            pid,
            "NetBox CMDB identity (all lab devices)",
            expr,
            description="Full NetBox inventory via OTLP labels.",
        )

    nb_url = DEFAULT_NETBOX_URL
    root = (
        "$map(["
        '["Device", results[0].name],'
        '["NetBox ID", $string(results[0].id)],'
        '["Status", results[0].status.value],'
        '["Site", results[0].site.name],'
        '["Role", results[0].role.name],'
        '["Manufacturer", results[0].device_type.manufacturer.name],'
        '["Device type", results[0].device_type.display],'
        '["Platform", results[0].platform.name],'
        '["Serial", results[0].serial],'
        '["Asset tag", results[0].asset_tag],'
        '["Primary IP", results[0].primary_ip.address],'
        '["Rack", results[0].rack.name],'
        '["URL", results[0].display_url]'
        '], function($p) {{"Field": $p[0], "Details": $p[1]}})'
    )
    infinity_spec = {
        "type": "json",
        "source": "url",
        "format": "table",
        "parser": "backend",
        "url": f"{nb_url}/api/dcim/devices/?name=${{instance}}&limit=1",
        "url_options": {"method": "GET", "data": ""},
        "root_selector": root,
        "columns": [
            {"selector": "Field", "text": "Field", "type": "string"},
            {"selector": "Details", "text": "Details", "type": "string"},
        ],
        "filters": [],
    }
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": "NetBox CMDB identity (selected device)",
            "description": (
                "Live NetBox REST via Infinity datasource `netbox-api`. "
                "Pick $instance = spine1/leaf1/…. Replace with official NetBox plugin later."
            ),
            "links": [
                {
                    "title": "Open device in NetBox",
                    "url": "${netbox_url}/dcim/devices/${netbox_id}/",
                    "type": "link",
                    "icon": "external link",
                    "tooltip": "",
                    "tags": [],
                    "asDropdown": False,
                    "targetBlank": True,
                    "includeVars": True,
                    "keepTime": False,
                }
            ],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": [
                        {
                            "kind": "PanelQuery",
                            "spec": {
                                "query": {
                                    "kind": "DataQuery",
                                    "group": "yesoreyeram-infinity-datasource",
                                    "version": "v0",
                                    "datasource": {"name": "netbox-api"},
                                    "spec": infinity_spec,
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
                "group": "table",
                "version": "",
                "spec": {
                    "options": {"cellHeight": "sm", "showHeader": True},
                    "fieldConfig": {
                        "defaults": {
                            "custom": {
                                "align": "auto",
                                "cellOptions": {"type": "auto"},
                                "inspect": False,
                                "wrapText": True,
                            }
                        },
                        "overrides": [
                            {
                                "matcher": {"id": "byName", "options": "Field"},
                                "properties": [{"id": "custom.width", "value": 140}],
                            }
                        ],
                    },
                },
            },
        },
    }


def netbox_fleet_table_panel(pid: int, title: str, expr: str, *, description: str = "") -> dict:
    """Wide inventory table — Prometheus table format already expands labels to columns."""
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": description,
            "links": [
                {
                    "title": "NetBox devices",
                    "url": "${netbox_url}/dcim/devices/",
                    "type": "link",
                    "icon": "external link",
                    "tooltip": "",
                    "tags": [],
                    "asDropdown": False,
                    "targetBlank": True,
                    "includeVars": False,
                    "keepTime": False,
                }
            ],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": [prom_query(expr, instant=True, fmt="table")],
                    "transformations": [
                        {
                            "kind": "Transformation",
                            "group": "organize",
                            "spec": {
                                "options": {
                                    "excludeByName": {
                                        "Time": True,
                                        "Value": True,
                                        "__name__": True,
                                        "job": True,
                                        "service_name": True,
                                        "deployment_host": True,
                                        "source": True,
                                        "site_slug": True,
                                        "asset_tag": True,
                                    },
                                    "indexByName": {
                                        "device_name": 0,
                                        "netbox_id": 1,
                                        "netbox_status": 2,
                                        "site": 3,
                                        "role": 4,
                                        "manufacturer": 5,
                                        "platform": 6,
                                        "primary_ip": 7,
                                        "serial": 8,
                                        "interface_count": 9,
                                        "tags": 10,
                                    },
                                    "renameByName": {
                                        "device_name": "Device",
                                        "netbox_id": "NetBox ID",
                                        "netbox_status": "Status",
                                        "site": "Site",
                                        "role": "Role",
                                        "manufacturer": "Manufacturer",
                                        "platform": "Platform",
                                        "primary_ip": "Primary IP",
                                        "serial": "Serial",
                                        "interface_count": "Ifaces (SoT)",
                                        "tags": "Tags",
                                    },
                                }
                            },
                        }
                    ],
                    "queryOptions": {},
                },
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": "table",
                "version": "",
                "spec": {
                    "options": {
                        "showHeader": True,
                        "cellHeight": "sm",
                        "footer": {
                            "show": False,
                            "reducer": ["sum"],
                            "countRows": False,
                        },
                    },
                    "fieldConfig": {
                        "defaults": {
                            "custom": {
                                "align": "auto",
                                "cellOptions": {"type": "auto"},
                                "inspect": False,
                            }
                        },
                        "overrides": [
                            {
                                "matcher": {"id": "byName", "options": "Device"},
                                "properties": [
                                    {
                                        "id": "links",
                                        "value": [
                                            {
                                                "title": "Open in NetBox",
                                                "url": (
                                                    "${netbox_url}/dcim/devices/"
                                                    "${__data.fields.NetBox ID}/"
                                                ),
                                                "targetBlank": True,
                                            },
                                            {
                                                "title": "Set as $instance",
                                                "url": (
                                                    "/d/ktranslate-device-details-netbox"
                                                    "?var-instance=${__value.raw}"
                                                ),
                                                "targetBlank": False,
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "matcher": {"id": "byName", "options": "NetBox ID"},
                                "properties": [
                                    {
                                        "id": "links",
                                        "value": [
                                            {
                                                "title": "Open device",
                                                "url": (
                                                    "${netbox_url}/dcim/devices/"
                                                    "${__value.raw}/"
                                                ),
                                                "targetBlank": True,
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    },
                },
            },
        },
    }


def netbox_table_panel(pid: int, title: str, expr: str, *, description: str = "") -> dict:
    """Back-compat wrapper → fleet table (wide label columns)."""
    return netbox_fleet_table_panel(pid, title, expr, description=description)


def stat_panel(pid: int, title: str, expr: str, *, description: str = "") -> dict:
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
                    "queries": [prom_query(expr, instant=True)],
                    "transformations": [],
                    "queryOptions": {},
                },
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": "stat",
                "version": "",
                "spec": {
                    "options": {
                        "reduceOptions": {
                            "calcs": ["lastNotNull"],
                            "fields": "",
                            "values": False,
                        },
                        "orientation": "auto",
                        "textMode": "auto",
                        "colorMode": "value",
                        "graphMode": "none",
                        "justifyMode": "auto",
                    },
                    "fieldConfig": {
                        "defaults": {
                            "unit": "short",
                            "thresholds": {
                                "mode": "absolute",
                                "steps": [
                                    {"value": 0, "color": "red"},
                                    {"value": 1, "color": "green"},
                                ],
                            },
                            "color": {"mode": "thresholds"},
                        },
                        "overrides": [],
                    },
                },
            },
        },
    }


def grid_item(name: str, *, x: int, y: int, w: int, h: int) -> dict:
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


def rows_row(title: str, items: list[dict], *, collapse: bool = False) -> dict:
    return {
        "kind": "RowsLayoutRow",
        "spec": {
            "title": title,
            "collapse": collapse,
            "hideHeader": False,
            "fillScreen": False,
            "layout": {"kind": "GridLayout", "spec": {"items": items}},
        },
    }


def add_constant_var(variables: list[dict], name: str, value: str, label: str) -> None:
    for v in variables:
        if (v.get("spec") or {}).get("name") == name:
            return
    variables.append(
        {
            "kind": "ConstantVariable",
            "spec": {
                "name": name,
                "query": value,
                "current": {"text": value, "value": value},
                "label": label,
                "hide": "dontHide",
                "skipUrlSync": False,
            },
        }
    )


def add_netbox_id_var(variables: list[dict]) -> None:
    for v in variables:
        if (v.get("spec") or {}).get("name") == "netbox_id":
            return
    # Mirror existing QueryVariable shape from Device Details (qryType label_values).
    variables.append(
        {
            "kind": "QueryVariable",
            "spec": {
                "name": "netbox_id",
                "current": {"text": "", "value": ""},
                "label": "NetBox ID",
                "hide": "hideVariable",
                "refresh": "onTimeRangeChanged",
                "skipUrlSync": False,
                "query": {
                    "kind": "DataQuery",
                    "group": "prometheus",
                    "version": "v0",
                    "datasource": {"name": "$datasource"},
                    "spec": {
                        "label": "netbox_id",
                        "labelFilters": [
                            {
                                "label": "device_name",
                                "op": "=~",
                                "value": "$instance",
                            },
                            {
                                "label": "service_name",
                                "op": "=",
                                "value": "netbox-inventory",
                            },
                        ],
                        "metric": "netbox_device_info",
                        "qryType": 1,
                        "query": (
                            "label_values(netbox_device_info{"
                            'device_name=~"$instance",'
                            'service_name="netbox-inventory"},netbox_id)'
                        ),
                        "refId": "PrometheusVariableQueryEditor-VariableQuery",
                    },
                },
                "regex": "",
                "regexApplyTo": "value",
                "sort": "alphabeticalAsc",
                "options": [],
                "multi": False,
                "includeAll": False,
                "allowCustomValue": True,
            },
        }
    )


def add_custom_var(variables: list[dict], name: str, value: str, label: str) -> None:
    # Kept for compatibility — prefer ConstantVariable in this stack.
    add_constant_var(variables, name, value, label)


def add_query_var(
    variables: list[dict],
    name: str,
    definition: str,
    *,
    label: str,
    hide: str = "dontHide",
) -> None:
    _ = (variables, name, definition, label, hide)
    # Deprecated helper — use add_netbox_id_var for NetBox ID.
    return


ENRICHMENT_MAP_MD = """### NetBox vs raw SNMP — where SoT adds value

This board is a **clone** of [04. Network Device Details](/d/ktranslate-device-details) with NetBox enrichment.
SNMP (`kentik_snmp_*`) answers *is it healthy / how busy*. NetBox answers *what is it supposed to be / where does it live / how is it wired*.

| Tab | SNMP already shows | NetBox enrichment (this board) | Deep link |
|-----|--------------------|--------------------------------|-----------|
| **NetBox SoT** (new) | — | CMDB identity: site, role, type, serial, rack, tenant, iface count | Device / site / IPAM pages |
| **Overview** | sysName, CPU/mem, poll health | Lifecycle status, role, site, manufacturer vs SNMP sysDescr | Device page |
| **Interfaces** | ifOperStatus, counters | Planned iface inventory count; cable/IP intent lives in NetBox | Device → Interfaces / IPAM |
| **Hardware Sensors** | ENTITY-SENSOR live readings | Asset identity (serial/type) — not sensor SoT | Device inventory |
| **Connections** | LLDP/BGP/OSPF *observed* adjacencies | *Intended* cabling / circuit SoT (when modeled) | Cables / connections |
| **Network Flow** | SNMP IP table + flow roles | Primary IP + IPAM ownership | IPAM addresses |
| **Events** | Syslog / traps | Change window / maintenance context (tags, status) | Device journal (UI) |
| **Telemetry** | Poller / profile / age | Discovery provenance: Orb → Diode → NetBox | NetBox device + Orb boards |

**Join key:** `device_name` (ktranslate) ↔ NetBox `name` (Orb discovery). Variable `$netbox_id` resolves from `netbox_device_info` for the selected `$instance`.

**Public NetBox UI:** [${netbox_url}](${netbox_url}/) (`admin` / `admin` from home IP allow-list).
"""


TAB_BANNERS: dict[str, str] = {
    "Overview": """### NetBox enrichment — Overview

| From SNMP (left / below) | From NetBox SoT |
|--------------------------|-----------------|
| `sysName` / `sysDescr` / uptime | Canonical **name**, **role**, **site**, **status** |
| Polling health | Lifecycle (`active` / planned / staged) |
| CPU / memory / disks | **Manufacturer / device type / platform / serial** (asset) |

**Open:** [Device in NetBox](${netbox_url}/dcim/devices/${netbox_id}/) · [Search by name](${netbox_url}/dcim/devices/?q=${instance}) · [Site](${netbox_url}/dcim/sites/?q=)
""",
    "Interfaces": """### NetBox enrichment — Interfaces

SNMP shows **live** oper/admin state and counters. NetBox holds the **planned** interface inventory, IP assignments, and (when modeled) cable endpoints.

| Live (SNMP) | SoT (NetBox) |
|-------------|--------------|
| ifHC* counters, errors/drops | Interface objects + descriptions |
| Oper state flaps | Expected connected endpoints |
| — | IPAM bindings on ifaces |

**Open:** [Device interfaces](${netbox_url}/dcim/interfaces/?device_id=${netbox_id}) · [IP addresses for device](${netbox_url}/ipam/ip-addresses/?device_id=${netbox_id}) · [Device](${netbox_url}/dcim/devices/${netbox_id}/)
""",
    "Hardware Sensors": """### NetBox enrichment — Hardware

Sensor *readings* stay on SNMP (`kentik_snmp_entity_sensor_*`, vendor MIBs). NetBox adds **what FRU/chassis this device is** (type, serial, rack/U) so a red fan sensor maps to an asset + location, not just a sysName.

**Open:** [Device inventory](${netbox_url}/dcim/devices/${netbox_id}/) · [Rack](${netbox_url}/dcim/racks/?q=)
""",
    "Connections": """### NetBox enrichment — Connections

| Observed (SNMP / gNMI) | Intended (NetBox) |
|------------------------|-------------------|
| LLDP remotes, BGP/OSPF neighbors | Cable / circuit / rear-port SoT |
| Adjacency flaps | Change control / documented peers |

When cables are modeled in NetBox, use them as the **intent** layer next to LLDP **observation**.

**Open:** [Device connections](${netbox_url}/dcim/devices/${netbox_id}/) · [Cables](${netbox_url}/dcim/cables/?device_id=${netbox_id}) · [Circuits](${netbox_url}/circuits/circuits/)
""",
    "Network Flow": """### NetBox enrichment — Addressing & flow identity

SNMP IP tables + ktranslate flows show **what is talking**. NetBox IPAM shows **who owns the address** (tenant, VRF, role) and the device primary IP used for management.

**Open:** [Primary device](${netbox_url}/dcim/devices/${netbox_id}/) · [IPAM search](${netbox_url}/ipam/ip-addresses/?q=) · [Prefixes](${netbox_url}/ipam/prefixes/)
""",
    "Events": """### NetBox enrichment — Events context

Syslog/traps remain the event stream. NetBox **status / tags / tenant** explain whether a flap is unexpected (production active) vs maintenance.

**Open:** [Device](${netbox_url}/dcim/devices/${netbox_id}/) · [Journal / changelog in NetBox UI](${netbox_url}/dcim/devices/${netbox_id}/)
""",
    "Telemetry": """### NetBox enrichment — Provenance

| Path | Signal |
|------|--------|
| ktranslate | Continuous SNMP poll → `kentik_snmp_*` |
| Orb → Diode → NetBox | Discovery reconcile → CMDB |
| `netbox-inventory-otlp` | `netbox_device_info` into Grafana |

**Open:** [NetBox device](${netbox_url}/dcim/devices/${netbox_id}/) · [Orb discovery dash](/d/orb-snmp-discovery) · [NetBox SoT dash](/d/netbox-inventory-sot) · [Leadership](/d/orb-ktranslate-entity-readiness)
""",
}


def prepend_banner_row(tab_spec: dict, panel_name: str, *, height: int = 7) -> None:
    layout = tab_spec.get("layout") or {}
    if layout.get("kind") != "RowsLayout":
        return
    rows = (layout.get("spec") or {}).setdefault("rows", [])
    banner = rows_row(
        "NetBox SoT enrichment",
        [grid_item(panel_name, x=0, y=0, w=24, h=height)],
        collapse=False,
    )
    rows.insert(0, banner)


def build_netbox_tab(elements: dict[str, Any], next_id: int) -> tuple[dict, int]:
    """Create the leading NetBox SoT tab + register elements. Returns (tab, next_id)."""
    panels: list[tuple[str, dict, int, int]] = []  # name, el, w, h

    def add(el: dict, w: int, h: int) -> str:
        nonlocal next_id
        pid = next_id
        next_id += 1
        name = f"panel-{pid}"
        el = copy.deepcopy(el)
        el["spec"]["id"] = pid
        elements[name] = el
        panels.append((name, el, w, h))
        return name

    add(
        text_panel(
            0,
            "Why NetBox on Device Details",
            ENRICHMENT_MAP_MD,
        ),
        24,
        12,
    )
    add(
        text_panel(
            0,
            "Deep links (selected device)",
            f"""### Jump to NetBox for `$instance`

| Page | Link |
|------|------|
| **Device** | [${{netbox_url}}/dcim/devices/${{netbox_id}}/](${{netbox_url}}/dcim/devices/${{netbox_id}}/) |
| **Interfaces** | […/dcim/interfaces/?device_id=…](${{netbox_url}}/dcim/interfaces/?device_id=${{netbox_id}}) |
| **IP addresses** | […/ipam/ip-addresses/?device_id=…](${{netbox_url}}/ipam/ip-addresses/?device_id=${{netbox_id}}) |
| **Cables** | […/dcim/cables/?device_id=…](${{netbox_url}}/dcim/cables/?device_id=${{netbox_id}}) |
| **Search by name** | […/dcim/devices/?q=$instance](${{netbox_url}}/dcim/devices/?q=${{instance}}) |
| **NetBox home** | [{DEFAULT_NETBOX_URL}](${{netbox_url}}/) |

`$netbox_id` is resolved from `netbox_device_info{{device_name=~"$instance"}}`.
If empty, Orb→Diode has not reconciled that name yet — check [22. NetBox inventory](/d/netbox-inventory-sot).
""",
        ),
        24,
        9,
    )

    add(
        stat_panel(
            0,
            "In NetBox SoT?",
            f'max(netbox_device_info{{{NB_SEL}}}) OR vector(0)',
            description="1 = device_name present in NetBox inventory export",
        ),
        4,
        4,
    )
    add(
        stat_panel(
            0,
            "NetBox devices (lab)",
            f'max(netbox_device_count{{{NB_ALL}}}) OR vector(0)',
        ),
        4,
        4,
    )
    add(
        stat_panel(
            0,
            "NetBox interfaces (lab)",
            f'max(netbox_interface_count{{{NB_ALL}}}) OR vector(0)',
        ),
        4,
        4,
    )
    add(
        stat_panel(
            0,
            "SNMP devices (group)",
            'count(count by (device_name) (kentik_snmp_CPU{snmp_group=~"$snmp_group"})) OR vector(0)',
        ),
        4,
        4,
    )
    add(
        stat_panel(
            0,
            "SNMP ifaces (selected)",
            'count(kentik_snmp_ifHCInOctets{snmp_group=~"$snmp_group",device_name=~"$instance"}) OR vector(0)',
            description="Live polled interfaces with in-octets — compare to NetBox iface count on the row below",
        ),
        4,
        4,
    )
    add(
        stat_panel(
            0,
            "NetBox ifaces (selected)",
            f'max(netbox_device_info{{{NB_SEL}}}) * 0 + '
            f'count(netbox_device_info{{{NB_SEL}}}) OR vector(0)',
            description="Presence gauge — per-device iface count is on the table (interface_count label)",
        ),
        4,
        4,
    )

    # Fix last stat — better expr for interface_count label as numeric via absent trick
    # Actually use: max by () (label replace) — Prom doesn't parse string labels as numbers easily.
    # Use: count won't work. Better panel title "see table". Replace with serial presence or status.
    elements[panels[-1][0]] = stat_panel(
        int(panels[-1][0].split("-")[1]),
        "NetBox IPAM addrs (lab)",
        f'max(netbox_ip_address_count{{{NB_ALL}}}) OR vector(0)',
    )

    add(
        netbox_identity_panel(0, selected=True),
        12,
        12,
    )
    add(
        netbox_fleet_table_panel(
            0,
            "All NetBox devices (lab SoT)",
            (
                "sum by (device_name, netbox_id, netbox_status, site, role, manufacturer, "
                "platform, primary_ip, serial, interface_count, tags) ("
                f"last_over_time(netbox_device_info{{{NB_ALL}}}[15m]))"
            ),
            description=(
                "Full inventory — click Device to open NetBox or set $instance. "
                "Lab names: spine1, leaf1, leaf2, leaf-br1, leaf-br2."
            ),
        ),
        12,
        12,
    )
    add(
        text_panel(
            0,
            "Side-by-side value proposition",
            """### What you cannot get from SNMP alone

1. **Stable identity** — sysName can drift; NetBox name + ID is the CMDB key for Knowledge Graph.
2. **Placement** — site / rack / location / tenant (SNMP has no standard rack SoT).
3. **Intended design** — device role, device type, platform SKU.
4. **Interface intent** — planned ports + IPAM; SNMP only sees what is currently configured/up.
5. **Wiring intent** — cables/circuits (LLDP is observation, not design).
6. **Lifecycle** — planned / staged / decommissioning vs “still answering SNMP”.

### What SNMP still owns

Continuous health: CPU, memory, interface counters/errors, sensors, BGP/OSPF/LLDP *state*, traps/syslog.
""",
        ),
        24,
        10,
    )

    # Layout rows
    names = [p[0] for p in panels]
    # 0 map, 1 links, 2-7 stats, 8 table selected, 9 table all, 10 value prop
    rows = [
        rows_row("Value map — NetBox over SNMP", [grid_item(names[0], x=0, y=0, w=24, h=12)]),
        rows_row("Deep links", [grid_item(names[1], x=0, y=0, w=24, h=9)]),
        rows_row(
            "Coverage — SoT vs live poll",
            [
                grid_item(names[2], x=0, y=0, w=4, h=4),
                grid_item(names[3], x=4, y=0, w=4, h=4),
                grid_item(names[4], x=8, y=0, w=4, h=4),
                grid_item(names[5], x=12, y=0, w=4, h=4),
                grid_item(names[6], x=16, y=0, w=4, h=4),
                grid_item(names[7], x=20, y=0, w=4, h=4),
            ],
        ),
        rows_row(
            "Selected device — CMDB attributes (Field / Details)",
            [
                grid_item(names[8], x=0, y=0, w=12, h=12),
                grid_item(names[9], x=12, y=0, w=12, h=12),
            ],
        ),
        rows_row("Talk track", [grid_item(names[10], x=0, y=0, w=24, h=10)]),
    ]
    tab = {
        "kind": "TabsLayoutTab",
        "spec": {
            "title": "NetBox SoT",
            "layout": {"kind": "RowsLayout", "spec": {"rows": rows}},
        },
    }
    return tab, next_id


def set_default_instance(variables: list[dict], device: str = "spine1") -> None:
    for v in variables:
        spec = v.get("spec") or {}
        if spec.get("name") != "instance":
            continue
        spec["current"] = {"text": device, "value": device}
        return


def inject_overview_cmdb(elements: dict[str, Any], tab_spec: dict, next_id: int) -> int:
    """After NetBox banner on Overview, add real CMDB Field/Details next to SNMP System Info story."""
    pid = next_id
    next_id += 1
    name = f"panel-{pid}"
    elements[name] = netbox_identity_panel(pid, selected=True)

    pid2 = next_id
    next_id += 1
    name2 = f"panel-{pid2}"
    elements[name2] = text_panel(
        pid2,
        "SNMP vs NetBox — same device",
        """### Read left → right

| Panel | Source | Question it answers |
|-------|--------|---------------------|
| **System Info** (below) | `kentik_snmp_*` labels | What did the box say about itself last poll? |
| **NetBox CMDB identity** (this row) | `netbox_device_info` | What does the CMDB say this device *is*? |

Pick `$instance` = `spine1` / `leaf1` / `leaf2` / `leaf-br1` / `leaf-br2` for SoT rows to populate.
Deep link: [Open in NetBox](${netbox_url}/dcim/devices/${netbox_id}/)
""",
    )

    layout = tab_spec.get("layout") or {}
    rows = (layout.get("spec") or {}).setdefault("rows", [])
    cmdb_row = rows_row(
        "NetBox CMDB metadata (live labels)",
        [
            grid_item(name, x=0, y=0, w=12, h=12),
            grid_item(name2, x=12, y=0, w=12, h=12),
        ],
    )
    # Insert after banner (index 0) if present, else at top
    insert_at = 1 if rows and (rows[0].get("spec") or {}).get("title") == "NetBox SoT enrichment" else 0
    rows.insert(insert_at, cmdb_row)
    return next_id


def enrich_clone(doc: dict) -> dict:
    out = copy.deepcopy(doc)
    meta = out.setdefault("metadata", {})
    meta["name"] = DST_UID
    meta["namespace"] = NS
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    labels = meta.setdefault("labels", {})
    labels.pop("grafana.app/deprecatedInternalID", None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER_UID
    ann["grafana.app/message"] = (
        "Clone of ktranslate-device-details with NetBox SoT enrichment + deep links"
    )

    spec = out.setdefault("spec", {})
    spec["title"] = "25. Device Details + NetBox SoT"
    spec["description"] = (
        "Clone of Network Device Details with NetBox CMDB enrichment. "
        "SNMP = live health; NetBox = inventory / placement / intent. "
        "Deep links use $netbox_url + $netbox_id for the selected $instance."
    )
    tags = list(spec.get("tags") or [])
    for t in ("netbox", "enrichment", "network-lab", "ktranslate"):
        if t not in tags:
            tags.append(t)
    spec["tags"] = tags

    # Dashboard links (v2 requires full DashboardLink shape — tags list always present)
    links = list(spec.get("links") or [])
    extra = [
        {
            "title": "NetBox UI",
            "url": "${netbox_url}/",
            "type": "link",
            "icon": "external link",
            "tooltip": "Open NetBox OSS",
            "tags": [],
            "asDropdown": False,
            "targetBlank": True,
            "includeVars": True,
            "keepTime": False,
        },
        {
            "title": "Original Device Details",
            "url": "/d/ktranslate-device-details",
            "type": "link",
            "icon": "dashboard",
            "tooltip": "Unmodified ktranslate Device Details",
            "tags": [],
            "asDropdown": False,
            "targetBlank": False,
            "includeVars": True,
            "keepTime": True,
        },
    ]
    # Keep existing links; prepend extras if not already present
    titles = {ln.get("title") for ln in links if isinstance(ln, dict)}
    for ln in reversed(extra):
        if ln["title"] not in titles:
            links.insert(0, ln)
    spec["links"] = links

    variables = list(spec.get("variables") or [])
    add_constant_var(variables, "netbox_url", DEFAULT_NETBOX_URL, "NetBox URL")
    add_netbox_id_var(variables)
    set_default_instance(variables, "spine1")
    spec["variables"] = variables

    elements = spec.setdefault("elements", {})
    next_id = max_panel_id(elements) + 1

    # Per-tab banners
    layout = spec.get("layout") or {}
    if layout.get("kind") != "TabsLayout":
        raise RuntimeError(f"expected TabsLayout, got {layout.get('kind')}")
    tabs = (layout.get("spec") or {}).setdefault("tabs", [])

    for tab in tabs:
        tspec = tab.get("spec") or {}
        title = tspec.get("title") or ""
        md = TAB_BANNERS.get(title)
        if not md:
            continue
        pid = next_id
        next_id += 1
        name = f"panel-{pid}"
        elements[name] = text_panel(pid, f"NetBox × {title}", md)
        prepend_banner_row(tspec, name, height=8 if title != "Overview" else 9)
        if title == "Overview":
            next_id = inject_overview_cmdb(elements, tspec, next_id)

    # Leading NetBox tab
    nb_tab, next_id = build_netbox_tab(elements, next_id)
    tabs.insert(0, nb_tab)

    return out


def upsert(env: dict[str, str], dash: dict) -> None:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{DST_UID}"
    code, existing = api(env, "GET", path)
    body = copy.deepcopy(dash)
    if code == 200 and isinstance(existing, dict):
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            body.setdefault("metadata", {})["resourceVersion"] = rv
        labels = (existing.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in labels:
            body.setdefault("metadata", {}).setdefault("labels", {})[
                "grafana.app/deprecatedInternalID"
            ] = labels["grafana.app/deprecatedInternalID"]
        code2, out = api(env, "PUT", path, body)
        action = "updated"
    else:
        body.get("metadata", {}).get("labels", {}).pop(
            "grafana.app/deprecatedInternalID", None
        )
        create = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards"
        code2, out = api(env, "POST", create, body)
        action = "created"
        if code2 == 409:
            code, existing = api(env, "GET", path)
            rv = (existing.get("metadata") or {}).get("resourceVersion")
            if rv:
                body.setdefault("metadata", {})["resourceVersion"] = rv
            code2, out = api(env, "PUT", path, body)
            action = "updated"
    if code2 not in (200, 201):
        raise RuntimeError(f"{action} failed HTTP {code2}: {out}")
    kind = ((out or {}).get("spec") or {}).get("layout", {}).get("kind")
    gen = ((out or {}).get("metadata") or {}).get("generation")
    print(f"{action} {DST_UID} layout={kind} generation={gen}")
    if kind != "TabsLayout":
        raise RuntimeError("TabsLayout lost — restore from version history")


def write_enrichment_doc(path: Path) -> None:
    path.write_text(
        "# Device Details × NetBox enrichment map\n\n"
        + ENRICHMENT_MAP_MD.replace("${netbox_url}", DEFAULT_NETBOX_URL)
        + "\n\n## Per-tab banners\n\n"
        + "\n".join(f"### {k}\n\n{v}\n" for k, v in TAB_BANNERS.items())
        + f"\n\nDashboard: `/d/{DST_UID}` · Folder: `{FOLDER_TITLE}` (`{FOLDER_UID}`)\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--source",
        type=Path,
        default=OUT / f"{SRC_UID}-live.json",
        help="Local live pull of device details (default: prior pull)",
    )
    args = ap.parse_args()
    if os.environ.get("FORCE_DEVICE_DETAILS_NETBOX_BUILD") != "1" and not args.dry_run:
        print(
            "Refusing to overwrite live 25 (Infinity NetBox panels). "
            "Set FORCE_DEVICE_DETAILS_NETBOX_BUILD=1 to override. "
            "Live path: split-device-details-netbox-panels.py + retarget-netbox-otlp-to-infinity.py",
            file=sys.stderr,
        )
        return 2
    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        print("GRAFANA_URL + GRAFANA_TOKEN required in local/.env", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    if args.source.is_file():
        doc = json.loads(args.source.read_text(encoding="utf-8"))
        print(f"loaded source {args.source}")
    else:
        code, doc = api(
            env,
            "GET",
            f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{SRC_UID}",
        )
        if code != 200:
            raise SystemExit(f"GET {SRC_UID} failed: {code} {doc}")
        args.source.parent.mkdir(parents=True, exist_ok=True)
        args.source.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"pulled {SRC_UID} -> {args.source}")

    enriched = enrich_clone(doc)
    staged = OUT / f"{DST_UID}.json"
    staged.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    doc_path = OUT / "enrichment-map.md"
    write_enrichment_doc(doc_path)
    # Also copy a stable docs path under local/docs
    docs = ROOT / "docs" / "device-details-netbox-enrichment.md"
    write_enrichment_doc(docs)
    print(f"staged {staged} ({staged.stat().st_size} bytes)")
    print(f"wrote {docs}")

    tabs = [
        (t.get("spec") or {}).get("title")
        for t in ((enriched.get("spec") or {}).get("layout") or {}).get("spec", {}).get(
            "tabs"
        )
        or []
    ]
    print("tabs:", tabs)
    print("elements:", len((enriched.get("spec") or {}).get("elements") or {}))

    if args.dry_run:
        print("dry-run — skip folder/create")
        return 0

    ensure_folder(env)
    upsert(env, enriched)
    url = f"{env['GRAFANA_URL'].rstrip('/')}/d/{DST_UID}"
    print(f"open: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
