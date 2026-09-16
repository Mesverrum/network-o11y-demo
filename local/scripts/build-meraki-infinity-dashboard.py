#!/usr/bin/env python3
"""Build an importable Grafana dashboard for Meraki Dashboard API v1 via Infinity.

Classic JSON (safe for first import). Infinity queries are GET-only snapshots —
not a timeseries store. Refresh defaults to 5m to stay under Meraki's org rate
limit (~10 req/s). Collapsed rows do not query until expanded.

Meraki API: https://developer.cisco.com/meraki/api-v1/

Usage:
  python3 local/scripts/build-meraki-infinity-dashboard.py
  python3 local/scripts/build-meraki-infinity-dashboard.py --import

Infinity datasource setup (Grafana Cloud proxy):
  URL: https://api.meraki.com/api/v1   (or regional: api.meraki.ca / .in / .cn)
  Auth: API key header X-Cisco-Meraki-API-Key
  allowedHosts: api.meraki.com
  Panel URLs are relative (no leading slash) so they append to /api/v1.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "infinity" / "meraki-api-infinity.json"
UID = "meraki-api-infinity"
TITLE = "Meraki Dashboard API (Infinity)"
FOLDER_UID = "network-lab"
FOLDER_TITLE = "Network Lab"

DS = {"type": "yesoreyeram-infinity-datasource", "uid": "${infinity}"}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def col(selector: str, text: str, typ: str = "string") -> dict[str, str]:
    return {"selector": selector, "text": text, "type": typ}


def inf_target(
    url: str,
    *,
    ref: str = "A",
    columns: list[dict[str, str]] | None = None,
    root: str = "",
    object_root: bool = False,
    uql: str | None = None,
) -> dict[str, Any]:
    t: dict[str, Any] = {
        "refId": ref,
        "datasource": DS,
        "type": "json",
        "source": "url",
        "url": url,
        "url_options": {"method": "GET", "data": ""},
        "format": "table",
        "root_selector": root,
        "columns": columns or [],
        "filters": [],
    }
    if uql:
        t["parser"] = "uql"
        t["uql"] = uql
    else:
        t["parser"] = "backend"
    if object_root:
        t["json_options"] = {"root_is_not_array": True, "columnar": False}
    return t


def var_query(name: str, label: str, url: str, text_sel: str, value_sel: str) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DS,
        "refresh": 1,
        "sort": 1,
        "regex": "",
        "includeAll": False,
        "multi": False,
        "hide": 0,
        "query": {
            "refId": f"var-{name}",
            "datasource": DS,
            "type": "json",
            "source": "url",
            "url": url,
            "url_options": {"method": "GET", "data": ""},
            "parser": "backend",
            "format": "table",
            "root_selector": "",
            "columns": [
                col(text_sel, "__text"),
                col(value_sel, "__value"),
            ],
            "filters": [],
        },
    }


def row(title: str, y: int, panel_id: int, *, collapsed: bool = False) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "row",
        "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": collapsed,
        "panels": [],
    }


def text_panel(pid: int, title: str, content: str, y: int, h: int = 6) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "text",
        "title": title,
        "gridPos": {"h": h, "w": 24, "x": 0, "y": y},
        "options": {"mode": "markdown", "content": content},
    }


def status_overrides(*field_names: str) -> list[dict[str, Any]]:
    mapping = {
        "type": "value",
        "options": {
            "online": {"color": "green", "index": 0, "text": "online"},
            "offline": {"color": "red", "index": 1, "text": "offline"},
            "alerting": {"color": "orange", "index": 2, "text": "alerting"},
            "dormant": {"color": "blue", "index": 3, "text": "dormant"},
            "active": {"color": "green", "index": 4, "text": "active"},
            "failed": {"color": "red", "index": 5, "text": "failed"},
            "connecting": {"color": "yellow", "index": 6, "text": "connecting"},
            "ready": {"color": "blue", "index": 7, "text": "ready"},
            "not connected": {"color": "purple", "index": 8, "text": "not connected"},
            "Connected": {"color": "green", "index": 9, "text": "Connected"},
            "Disconnected": {"color": "red", "index": 10, "text": "Disconnected"},
            "critical": {"color": "red", "index": 11, "text": "critical"},
            "warning": {"color": "orange", "index": 12, "text": "warning"},
            "informational": {"color": "blue", "index": 13, "text": "informational"},
            "OK": {"color": "green", "index": 14, "text": "OK"},
            "License Expiring Soon": {"color": "orange", "index": 15, "text": "expiring soon"},
            "License Expired": {"color": "red", "index": 16, "text": "expired"},
        },
    }
    overrides = []
    for name in field_names:
        overrides.append(
            {
                "matcher": {"id": "byName", "options": name},
                "properties": [
                    {"id": "mappings", "value": [mapping]},
                    {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                ],
            }
        )
    return overrides


def hide_time() -> list[dict[str, Any]]:
    return [
        {
            "id": "organize",
            "options": {
                "excludeByName": {"Time": True, "time": True},
                "renameByName": {},
            },
        }
    ]


def stat_panel(
    pid: int,
    title: str,
    url: str,
    columns: list[dict[str, str]],
    y: int,
    x: int,
    w: int,
    *,
    description: str = "",
    unit: str = "",
) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "description": description,
        "gridPos": {"h": 5, "w": w, "x": x, "y": y},
        "datasource": DS,
        "targets": [inf_target(url, columns=columns, object_root=True)],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "textMode": "auto",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "orange", "value": 1},
                        {"color": "red", "value": 5},
                    ],
                },
            },
            "overrides": [],
        },
        "transformations": hide_time(),
    }


def table_panel(
    pid: int,
    title: str,
    url: str,
    columns: list[dict[str, str]] | None,
    y: int,
    h: int = 10,
    *,
    description: str = "",
    object_root: bool = False,
    uql: str | None = None,
    status_fields: tuple[str, ...] = ("status",),
    w: int = 24,
    x: int = 0,
) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "description": description,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": DS,
        "targets": [
            inf_target(url, columns=columns, object_root=object_root, uql=uql)
        ],
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
        "fieldConfig": {
            "defaults": {"custom": {"filterable": True, "inspect": False}},
            "overrides": status_overrides(*status_fields) if status_fields else [],
        },
        "transformations": hide_time(),
    }


HOWTO = """\
**Infinity datasource** (pick `$infinity` above). Base URL must be `https://api.meraki.com/api/v1` (Canada `api.meraki.ca`, India `api.meraki.in`, China `api.meraki.cn`). Auth header **`X-Cisco-Meraki-API-Key`**. Add the API host to Infinity **allowedHosts**. GET only.

This board is a **live snapshot** of [Meraki Dashboard API v1](https://developer.cisco.com/meraki/api-v1/) monitor endpoints — same pattern as NetBox Infinity. It is **not** historical telemetry (use SNMP / the Meraki plugin / webhooks for that).

| Row | Endpoints |
|---|---|
| Fleet | `GET /organizations/{id}/devices/statuses/overview`, `…/appliance/uplinks/statuses/overview`, `…/clients/overview`, `…/licenses/overview`, `…/assurance/alerts/overview` |
| Devices | `GET /organizations/{id}/devices/availabilities` (replacement for deprecated `…/devices/statuses`) |
| Networks | `GET /organizations/{id}/summary/top/networks/byStatus` |
| WAN | `GET /organizations/{id}/appliance/uplink/statuses`, `…/devices/uplinksLossAndLatency` |
| Top talkers | `…/summary/top/{devices,clients,ssids,applications}/byUsage` |
| Alerts | `GET /organizations/{id}/assurance/alerts?active=true` |
| Network | `GET /networks/{id}/clients`, `…/wireless/ssids`, `…/wireless/connectionStats`, `…/wireless/failedConnections` |
| Switch | `GET /devices/{serial}/switch/ports/statuses` |

**Limits:** first page only (`perPage=1000`). Meraki ~10 req/s/org — keep refresh at **5m**. Expand extra rows only when you need them. Usage values from clients/overview are **kilobytes**.
"""


def build() -> dict[str, Any]:
    org = "${orgId}"
    net = "${networkId}"
    serial = "${serial}"
    ts = "${timespan}"

    panels: list[dict[str, Any]] = []
    y = 0

    def add_row(title: str, pid: int, children: list[dict[str, Any]], *, collapsed: bool) -> None:
        nonlocal y
        r = row(title, y, pid, collapsed=collapsed)
        if collapsed:
            r["panels"] = children
            panels.append(r)
            y += 1
            return
        r["panels"] = []
        panels.append(r)
        y += 1
        for child in children:
            panels.append(child)
        if children:
            last = children[-1]
            gp = last["gridPos"]
            y = gp["y"] + gp["h"]

    panels.append(text_panel(1, "How this board works", HOWTO, y, h=8))
    y += 8

    cy = y + 1
    add_row(
        "Fleet overview",
        2,
        [
            stat_panel(
                3,
                "Devices by status",
                f"organizations/{org}/devices/statuses/overview",
                [
                    col("counts.online", "online", "number"),
                    col("counts.offline", "offline", "number"),
                    col("counts.alerting", "alerting", "number"),
                    col("counts.dormant", "dormant", "number"),
                ],
                cy,
                0,
                6,
                description="GET /organizations/{id}/devices/statuses/overview",
            ),
            stat_panel(
                4,
                "MX / Z uplinks",
                f"organizations/{org}/appliance/uplinks/statuses/overview",
                [
                    col("counts.byStatus.active", "active", "number"),
                    col("counts.byStatus.failed", "failed", "number"),
                    col("counts.byStatus.connecting", "connecting", "number"),
                    col("counts.byStatus.notConnected", "not connected", "number"),
                ],
                cy,
                6,
                6,
                description="GET /organizations/{id}/appliance/uplinks/statuses/overview",
            ),
            stat_panel(
                5,
                "Clients (timespan)",
                f"organizations/{org}/clients/overview?timespan={ts}",
                [
                    col("counts.total", "clients", "number"),
                    col("usage.overall.total", "usage_kb", "number"),
                ],
                cy,
                12,
                4,
                description="GET /organizations/{id}/clients/overview — usage is kilobytes",
            ),
            stat_panel(
                6,
                "Assurance alerts",
                f"organizations/{org}/assurance/alerts/overview?active=true",
                [
                    col("counts.total", "active", "number"),
                    col("counts.bySeverity.critical", "critical", "number"),
                    col("counts.bySeverity.warning", "warning", "number"),
                ],
                cy,
                16,
                4,
                description="GET /organizations/{id}/assurance/alerts/overview?active=true",
            ),
            stat_panel(
                7,
                "Licenses",
                f"organizations/{org}/licenses/overview",
                [
                    col("status", "status", "string"),
                    col("licenseCount", "licenses", "number"),
                    col("states.expired", "expired", "number"),
                    col("states.expiring", "expiring", "number"),
                ],
                cy,
                20,
                4,
                description="GET /organizations/{id}/licenses/overview — co-term vs per-device shapes differ",
            ),
        ],
        collapsed=False,
    )

    cy = y + 1
    add_row(
        "Devices",
        10,
        [
            table_panel(
                11,
                "Device availability",
                f"organizations/{org}/devices/availabilities?perPage=1000",
                [
                    col("name", "name"),
                    col("serial", "serial"),
                    col("status", "status"),
                    col("productType", "productType"),
                    col("network.name", "network"),
                    col("network.id", "networkId"),
                    col("mac", "mac"),
                ],
                cy,
                h=12,
                description=(
                    "GET /organizations/{id}/devices/availabilities — updates every 5 minutes. "
                    "Use this instead of deprecated GET …/devices/statuses."
                ),
            )
        ],
        collapsed=False,
    )

    cy = y + 1
    add_row(
        "Networks",
        20,
        [
            table_panel(
                21,
                "Networks by status",
                f"organizations/{org}/summary/top/networks/byStatus?perPage=1000",
                [
                    col("name", "network"),
                    col("networkId", "networkId"),
                    col("statuses.online", "online", "number"),
                    col("statuses.offline", "offline", "number"),
                    col("statuses.alerting", "alerting", "number"),
                    col("statuses.dormant", "dormant", "number"),
                    col("clients.counts.total", "clients", "number"),
                    col("usage.overall.total", "usage", "number"),
                ],
                cy,
                h=10,
                description="GET /organizations/{id}/summary/top/networks/byStatus",
                status_fields=(),
            )
        ],
        collapsed=False,
    )

    cy = y + 1
    add_row(
        "WAN / appliance uplinks",
        30,
        [
            table_panel(
                31,
                "MX / Z uplink status",
                f"organizations/{org}/appliance/uplink/statuses?perPage=1000",
                None,
                cy,
                h=10,
                description="GET /organizations/{id}/appliance/uplink/statuses — one row per WAN interface",
                uql=(
                    "parse-json\n"
                    '| mv-expand "uplinks"\n'
                    '| project "serial", "model", "networkId", "lastReportedAt", '
                    '"ha"="highAvailability.role", '
                    '"interface"="uplinks.interface", "status"="uplinks.status", '
                    '"ip"="uplinks.ip", "publicIp"="uplinks.publicIp", '
                    '"gateway"="uplinks.gateway"'
                ),
            ),
            table_panel(
                32,
                "Uplink loss and latency (MX)",
                f"organizations/{org}/devices/uplinksLossAndLatency?timespan={ts}",
                [
                    col("serial", "serial"),
                    col("networkId", "networkId"),
                    col("uplink", "uplink"),
                    col("ip", "ip"),
                    col("lossPercent", "lossPercent", "number"),
                    col("latencyMs", "latencyMs", "number"),
                ],
                cy + 10,
                h=8,
                description="GET /organizations/{id}/devices/uplinksLossAndLatency — latest sample; timeSeries is not graphed here",
                status_fields=(),
            ),
        ],
        collapsed=True,
    )

    cy = y + 1
    add_row(
        "Top talkers",
        40,
        [
            table_panel(
                41,
                "Top devices by usage",
                f"organizations/{org}/summary/top/devices/byUsage?timespan={ts}",
                [
                    col("name", "name"),
                    col("serial", "serial"),
                    col("model", "model"),
                    col("productType", "productType"),
                    col("network.name", "network"),
                    col("usage.total", "usage", "number"),
                    col("usage.percentage", "pct", "number"),
                    col("clients.counts.total", "clients", "number"),
                ],
                cy,
                h=8,
                w=12,
                x=0,
                description="GET /organizations/{id}/summary/top/devices/byUsage (top 10)",
                status_fields=(),
            ),
            table_panel(
                42,
                "Top clients by usage",
                f"organizations/{org}/summary/top/clients/byUsage?timespan={ts}",
                [
                    col("name", "name"),
                    col("mac", "mac"),
                    col("network.name", "network"),
                    col("usage.total", "usage_mb", "number"),
                    col("usage.upstream", "up", "number"),
                    col("usage.downstream", "down", "number"),
                    col("usage.percentage", "pct", "number"),
                ],
                cy,
                h=8,
                w=12,
                x=12,
                description="GET /organizations/{id}/summary/top/clients/byUsage — usage in MB",
                status_fields=(),
            ),
            table_panel(
                43,
                "Top SSIDs by usage",
                f"organizations/{org}/summary/top/ssids/byUsage?timespan={ts}",
                [
                    col("name", "ssid"),
                    col("usage.total", "usage", "number"),
                    col("usage.percentage", "pct", "number"),
                    col("clients.counts.total", "clients", "number"),
                ],
                cy + 8,
                h=8,
                w=12,
                x=0,
                description="GET /organizations/{id}/summary/top/ssids/byUsage",
                status_fields=(),
            ),
            table_panel(
                44,
                "Top applications by usage",
                f"organizations/{org}/summary/top/applications/byUsage?timespan={ts}",
                [
                    col("application", "application"),
                    col("total", "total", "number"),
                    col("downstream", "down", "number"),
                    col("upstream", "up", "number"),
                    col("percentage", "pct", "number"),
                ],
                cy + 8,
                h=8,
                w=12,
                x=12,
                description="GET /organizations/{id}/summary/top/applications/byUsage",
                status_fields=(),
            ),
        ],
        collapsed=True,
    )

    cy = y + 1
    add_row(
        "Assurance alerts",
        50,
        [
            table_panel(
                51,
                "Active health alerts",
                f"organizations/{org}/assurance/alerts?active=true&perPage=1000",
                [
                    col("severity", "severity"),
                    col("title", "title"),
                    col("categoryType", "category"),
                    col("type", "type"),
                    col("deviceType", "deviceType"),
                    col("serial", "serial"),
                    col("network.name", "network"),
                    col("startedAt", "startedAt"),
                ],
                cy,
                h=10,
                description="GET /organizations/{id}/assurance/alerts?active=true",
                status_fields=("severity",),
            )
        ],
        collapsed=True,
    )

    cy = y + 1
    add_row(
        "Licenses",
        60,
        [
            table_panel(
                61,
                "License inventory",
                f"organizations/{org}/licenses?perPage=1000",
                [
                    col("licenseType", "licenseType"),
                    col("state", "status"),
                    col("deviceSerial", "deviceSerial"),
                    col("networkId", "networkId"),
                    col("expirationDate", "expirationDate"),
                    col("seatCount", "seats", "number"),
                ],
                cy,
                h=8,
                description="GET /organizations/{id}/licenses — empty on some co-term orgs; use the overview stat instead",
            )
        ],
        collapsed=True,
    )

    cy = y + 1
    add_row(
        "Selected network — clients & wireless",
        70,
        [
            stat_panel(
                71,
                "Network clients",
                f"networks/{net}/clients/overview?timespan={ts}",
                [
                    col("counts.total", "clients", "number"),
                    col("counts.withHeavyUsage", "heavy", "number"),
                ],
                cy,
                0,
                6,
                description="GET /networks/{id}/clients/overview",
            ),
            stat_panel(
                72,
                "Wireless connection stats",
                f"networks/{net}/wireless/connectionStats?timespan={ts}",
                [
                    col("success", "success", "number"),
                    col("assoc", "assoc_fail", "number"),
                    col("auth", "auth_fail", "number"),
                    col("dhcp", "dhcp_fail", "number"),
                    col("dns", "dns_fail", "number"),
                ],
                cy,
                6,
                18,
                description="GET /networks/{id}/wireless/connectionStats — empty on non-wireless networks",
            ),
            table_panel(
                73,
                "Network clients",
                f"networks/{net}/clients?timespan={ts}&perPage=1000",
                [
                    col("description", "description"),
                    col("mac", "mac"),
                    col("ip", "ip"),
                    col("status", "status"),
                    col("ssid", "ssid"),
                    col("vlan", "vlan", "number"),
                    col("os", "os"),
                    col("manufacturer", "manufacturer"),
                    col("recentDeviceName", "ap_or_switch"),
                    col("usage.recv", "recv_kb", "number"),
                    col("usage.sent", "sent_kb", "number"),
                ],
                cy + 5,
                h=10,
                description="GET /networks/{id}/clients — Online/Offline in status; usage in KB",
            ),
            table_panel(
                74,
                "SSIDs",
                f"networks/{net}/wireless/ssids",
                [
                    col("number", "number", "number"),
                    col("name", "name"),
                    col("enabled", "enabled"),
                    col("authMode", "authMode"),
                    col("bandSelection", "band"),
                    col("visible", "visible"),
                    col("ipAssignmentMode", "ipAssignment"),
                ],
                cy + 15,
                h=8,
                w=12,
                x=0,
                description="GET /networks/{id}/wireless/ssids",
                status_fields=(),
            ),
            table_panel(
                75,
                "Failed wireless connections",
                f"networks/{net}/wireless/failedConnections?timespan={ts}",
                [
                    col("ts", "ts"),
                    col("type", "type"),
                    col("failureStep", "failureStep"),
                    col("clientMac", "clientMac"),
                    col("serial", "ap"),
                    col("ssidNumber", "ssid", "number"),
                    col("vlan", "vlan", "number"),
                ],
                cy + 15,
                h=8,
                w=12,
                x=12,
                description="GET /networks/{id}/wireless/failedConnections",
                status_fields=(),
            ),
        ],
        collapsed=True,
    )

    cy = y + 1
    add_row(
        "Selected switch — port status",
        80,
        [
            table_panel(
                81,
                "Switch port statuses",
                f"devices/{serial}/switch/ports/statuses?timespan={ts}",
                [
                    col("portId", "port"),
                    col("status", "status"),
                    col("enabled", "enabled"),
                    col("isUplink", "uplink"),
                    col("speed", "speed"),
                    col("duplex", "duplex"),
                    col("clientCount", "clients", "number"),
                    col("trafficInKbps.total", "kbps", "number"),
                    col("poe.isAllocated", "poe"),
                    col("lldp.systemName", "lldp_neighbor"),
                ],
                cy,
                h=12,
                description="GET /devices/{serial}/switch/ports/statuses — pick an MS serial. Errors on MR/MX are expected.",
            )
        ],
        collapsed=True,
    )

    return {
        "uid": UID,
        "title": TITLE,
        "tags": ["meraki", "infinity", "network"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 0,
        "refresh": "5m",
        "time": {"from": "now-24h", "to": "now"},
        "graphTooltip": 1,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "liveNow": False,
        "style": "dark",
        "panels": panels,
        "templating": {
            "list": [
                {
                    "name": "infinity",
                    "label": "Infinity (Meraki)",
                    "type": "datasource",
                    "query": "yesoreyeram-infinity-datasource",
                    "refresh": 1,
                    "hide": 0,
                    "current": {"text": "", "value": ""},
                    "includeAll": False,
                    "multi": False,
                },
                var_query("orgId", "Organization", "organizations", "name", "id"),
                var_query(
                    "networkId",
                    "Network",
                    f"organizations/{org}/networks?perPage=1000",
                    "name",
                    "id",
                ),
                var_query(
                    "serial",
                    "Switch serial",
                    f"organizations/{org}/devices?perPage=1000&productTypes=switch",
                    "name",
                    "serial",
                ),
                {
                    "name": "timespan",
                    "label": "Timespan",
                    "type": "custom",
                    "query": "1h : 3600, 24h : 86400, 7d : 604800",
                    "current": {"text": "24h", "value": "86400", "selected": True},
                    "options": [
                        {"text": "1h", "value": "3600", "selected": False},
                        {"text": "24h", "value": "86400", "selected": True},
                        {"text": "7d", "value": "604800", "selected": False},
                    ],
                    "includeAll": False,
                    "multi": False,
                    "hide": 0,
                },
            ]
        },
        "annotations": {"list": []},
        "links": [
            {
                "title": "Meraki API v1",
                "url": "https://developer.cisco.com/meraki/api-v1/",
                "type": "link",
                "icon": "doc",
                "targetBlank": True,
            }
        ],
        "description": (
            "Live Meraki Dashboard API v1 via Grafana Infinity. "
            "Select the Infinity datasource provisioned with X-Cisco-Meraki-API-Key. "
            "Refresh 5m. First 1000 records per collection."
        ),
    }


def api_request(base: str, token: str, method: str, path: str, body: object | None = None):
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw.decode(errors="replace")
        return e.code, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="POST to GRAFANA_URL (classic /api/dashboards/db)",
    )
    args = parser.parse_args()

    dash = build()
    dash.pop("id", None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")

    if not args.do_import:
        print(
            "Import: Grafana Dashboards > Import > "
            f"{OUT.as_posix()}\n"
            f"Or: python3 {Path(__file__).as_posix()} --import"
        )
        return 0

    env = load_env()
    base = env.get("GRAFANA_URL", "").rstrip("/")
    token = env.get("GRAFANA_TOKEN", "")
    if not base or not token:
        print("ERROR: set GRAFANA_URL and GRAFANA_TOKEN in local/.env")
        return 1

    code, _ = api_request(base, token, "GET", f"/api/folders/{FOLDER_UID}")
    if code != 200:
        code, out = api_request(
            base, token, "POST", "/api/folders", {"uid": FOLDER_UID, "title": FOLDER_TITLE}
        )
        if code not in (200, 409, 412):
            raise SystemExit(f"create folder failed HTTP {code}: {out}")

    payload = {"dashboard": dash, "folderUid": FOLDER_UID, "overwrite": True}
    code, out = api_request(base, token, "POST", "/api/dashboards/db", payload)
    if not (200 <= code < 300):
        print(f"FAILED HTTP {code}: {out}")
        return 1
    url = out.get("url", "") if isinstance(out, dict) else ""
    print(f"imported {TITLE} uid={UID} HTTP {code} {base}{url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
