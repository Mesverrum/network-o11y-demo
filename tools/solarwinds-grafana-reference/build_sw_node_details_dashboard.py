#!/usr/bin/env python3
"""Build + push SW: Node Details — full Orion view-group clone with TabsLayout.

Every classic widget from out/latest Node Details export gets a Grafana panel
(best-effort SWQL or markdown note). Tabs mirror Orion subviews.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sw_dashboard_links import LINK_ID_FIELDS, dashboard_nav_links, merge_table_overrides

ROOT = Path(__file__).resolve().parent
INVENTORY = ROOT / "out" / "latest" / "docs" / "node-details-widget-inventory.json"
STATUSINFO_PATH = ROOT / "swql_library" / "statusinfo.json"
DS_UID = "cfuwljtvzdclcb"
DS_TYPE = "grafana-solarwinds-datasource"
FOLDER_UID = "cf8311my2in7kf"
DASH_UID = "sw-node-details-summary"
DASH_TITLE = "SW: Node Details"
NS = "stacks-1061129"

# Internal keys — hide in Grafana tables (node already selected via $node_id)
HIDE_FIELD_REGEXP = (
    r"(?i)^(AlertObjectID|AlertID|"
    r"EventID|DependencyID|NetObjectID|AuditEventID|AccountID|"
    r"ActionTypeID|EngineID|Id|MapID|PortID|APID|VlanID|VRFID|RouteID|"
    r"NeighborID|HardwareInfoID|SysName)$"
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


# ---------------------------------------------------------------------------
# SWQL guesses — keyed by normalized title / resourceFile fragment
# ---------------------------------------------------------------------------

N = "$node_id"  # Grafana template var (plugin substitutes)
NODE_STUB = (
    f"SELECT Status, StatusDescription, MachineType, Vendor, "
    f"CPULoad, PercentMemoryUsed, ResponseTime, PercentLoss "
    f"FROM Orion.Nodes WHERE NodeID = {N}"
)


def load_statusinfo() -> list[dict[str, Any]]:
    if STATUSINFO_PATH.exists():
        data = json.loads(STATUSINFO_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data
    return []


def status_value_mappings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Grafana value mappings from Orion.StatusInfo (id → name + color)."""
    options: dict[str, Any] = {}
    for i, row in enumerate(rows):
        sid = row.get("StatusId")
        if sid is None:
            continue
        name = row.get("ShortDescription") or row.get("StatusName") or str(sid)
        color = row.get("Color") or "#999999"
        options[str(sid)] = {"text": str(name), "color": color, "index": i}
        # also map by StatusName text for StatusDescription-like fields
        sname = row.get("StatusName")
        if sname and str(sname) not in options:
            options[str(sname)] = {"text": str(name), "color": color, "index": i}
        short = row.get("ShortDescription")
        if short and str(short) not in options:
            options[str(short)] = {"text": str(name), "color": color, "index": i}
    return [{"type": "value", "options": options}]


def status_field_overrides(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mappings = status_value_mappings(rows)
    overrides: list[dict[str, Any]] = [
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
        {
            # Exact StatusName / ShortDescription cells (when SWQL returns those labels)
            "matcher": {"id": "byRegexp", "options": "(?i)^(StatusName|ShortDescription)$"},
            "properties": [
                {"id": "mappings", "value": mappings},
                {
                    "id": "custom.cellOptions",
                    "value": {"type": "color-background", "mode": "basic"},
                },
            ],
        },
    ]
    return overrides


def table_transforms_hide_ids() -> list[dict[str, Any]]:
    """Hide non-link IDs via organize; keep LINK_ID_FIELDS for data links."""
    exclude = {
        k: True
        for k in (
            "AlertObjectID",
            "AlertID",
            "EventID",
            "DependencyID",
            "NetObjectID",
            "AuditEventID",
            "AccountID",
            "ActionTypeID",
            "EngineID",
            "Id",
            "MapID",
        )
        if k not in LINK_ID_FIELDS
    }
    return [
        {
            "id": "organize",
            "options": {
                "excludeByName": exclude,
                "indexByName": {},
                "renameByName": {},
            },
        }
    ]


def guess_swql(title: str, name: str, file: str) -> tuple[str | None, str, str]:
    """Return (swql_or_None, note, viz). viz: table | markdown | timeseries[:unit]."""
    t = (title or "").lower()
    n = (name or "").lower()
    f = (file or "").replace("\\", "/").lower()
    blob = f"{t} | {n} | {f}"

    # Pure Orion UI / chrome — no SWQL
    ui_markers = (
        "managementtasks",
        "gettingstarted",
        "downloadconfig",
        "uploadconfig",
        "executescript",
        "compareconfigs",
        "configchangereport",
        "vmantools",
        "/management.ascx",
    )
    if any(m in f for m in ui_markers) or t in {"management", "download config", "upload config", "execute script", "compare configs"}:
        return None, "Orion UI action/chrome widget — no SWQL equivalent.", "markdown"

    # --- Core NPM node ---
    if "nodedetails.ascx" in f and "ncm" not in f:
        return (
            f"SELECT IP_Address, DNS, Vendor, MachineType, Status, StatusDescription, "
            f"CPULoad, PercentMemoryUsed, MemoryUsed, MemoryAvailable, ResponseTime, PercentLoss, "
            f"LastSync, NextPoll, IOSVersion, Location, Contact, Description "
            f"FROM Orion.Nodes WHERE NodeID = {N}",
            "Orion.Nodes snapshot",
            "table",
        )
    if "nodepollingdetails" in f or t == "polling details":
        return (
            f"SELECT ObjectSubType, PollInterval, StatCollection, RediscoveryInterval, "
            f"NextPoll, LastSync, Community FROM Orion.Nodes WHERE NodeID = {N}",
            "polling fields on Orion.Nodes",
            "table",
        )
    if "nodeipaddresses" in f or "all ip addresses" in t:
        return (
            f"SELECT SUB.IPAddressType, SUB.IP_Address2 AS IP_Address FROM ("
            f" SELECT IP_Address AS IP_Address2, IPAddressType, 1 AS IPOrder FROM Orion.Nodes WHERE NodeID = {N}"
            f" UNION (SELECT ni.IPAddress AS IP_Address2, ni.IPAddressType AS IPAddressType, 2 AS IPOrder "
            f" FROM Orion.NodeIPAddresses ni "
            f" JOIN Orion.Nodes n ON ni.NodeID = n.NodeID AND n.IP_Address != ni.IPAddress WHERE ni.NodeID = {N})"
            f") SUB ORDER BY SUB.IPOrder",
            "NodeIPAddresses union",
            "table",
        )
    if "nodecustomproperties" in f or "custom properties" in t:
        return (
            NODE_STUB,
            "Custom properties entity often missing; node stub",
            "table",
        )
    if "activealerts" in f and "cloud" not in f and "transaction" not in f and "virtualization" not in f:
        return (
            f"SELECT aa.AlertActiveID, o.RelatedNodeId, a.Name AS AlertName, aa.TriggeredMessage, aa.TriggeredDateTime, o.EntityCaption FROM Orion.AlertActive aa JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID WHERE o.RelatedNodeId = {N} ORDER BY aa.TriggeredDateTime DESC",
            "AlertActive by RelatedNodeId",
            "table",
        )
    if "allalertthisobjectcantrigger" in f or "all alerts this object" in t:
        return (
            f"SELECT a.Name, a.Severity, a.Enabled, a.ObjectType "
            f"FROM Orion.AlertConfigurations a WHERE a.Enabled = 1 ORDER BY a.Name",
            "enabled alert configs (not node-scoped in SWQL easily)",
            "table",
        )
    if "availabilitystats" in f or "availability statistics" in t:
        return (
            f"SELECT DateTime, AvgResponseTime, PercentLoss "
            f"FROM Orion.ResponseTime WHERE NodeID = {N} ORDER BY DateTime",
            "availability → ResponseTime history",
            "timeseries:ms",
        )
    if "interfaceutilization" in f or "percent utilization of each interface" in t:
        return (
            f"SELECT InterfaceID, NodeID, Caption, Name, Status, StatusDescription, InPercentUtil, OutPercentUtil, Inbps, Outbps, InErrorsThisHour, OutErrorsThisHour FROM Orion.NPM.Interfaces WHERE NodeID = {N} ORDER BY Caption",
            "NPM.Interfaces util",
            "table",
        )
    if "volumes.ascx" in f or t in {"disk volumes", "volumes"} or "percent disk space" in t:
        return (
            f"SELECT VolumeID, NodeID, Caption, VolumeType, VolumePercentUsed, VolumeSize, VolumeSpaceUsed, VolumeSpaceAvailable, Status FROM Orion.Volumes WHERE NodeID = {N} ORDER BY VolumePercentUsed DESC",
            "Orion.Volumes",
            "table",
        )
    if "cpusbypercentload" in f or t == "cpus by percent load":
        return (
            f"SELECT CPULoad, CPUCount FROM Orion.Nodes WHERE NodeID = {N}",
            "per-CPU entity may be absent; node CPULoad",
            "table",
        )
    if "top cpus by percent load" in t:
        return (
            f"SELECT DateTime, AvgLoad, MaxLoad "
            f"FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
            "Top CPUs chart → CPULoad history",
            "timeseries:percent",
        )
    if "duplexmismatch" in f or "duplex mismatch" in t:
        return (
            f"SELECT Caption, FullName, DuplexMode, Status, StatusDescription "
            f"FROM Orion.NPM.Interfaces WHERE NodeID = {N} ORDER BY Caption",
            "duplex fields if present on Interfaces",
            "table",
        )
    if "nodedependencies" in f or "dependencies" in t:
        return (
            f"SELECT ParentUri, ChildUri FROM Orion.Dependencies",
            "all dependencies (filter by node URI in UI)",
            "table",
        )
    if "nodemapstable" in f or "all maps with node" in t:
        return (
            NODE_STUB,
            "Orion.Maps not in this catalog — node stub",
            "table",
        )
    if "eventsummary" in f or t == "event summary":
        return (
            f"SELECT TOP 50 EventTime, Message, EventType "
            f"FROM Orion.Events WHERE NetObjectID = {N} ORDER BY EventTime DESC",
            "Orion.Events for node",
            "table",
        )
    if "lastxxauditevents" in f or "audit events" in t:
        return (
            f"SELECT TOP 50 TimeLoggedUtc, AuditEventMessage "
            f"FROM Orion.AuditingEvents ORDER BY TimeLoggedUtc DESC",
            "recent audit events (not always node-scoped)",
            "table",
        )
    if "noteshistory" in f or "last xx notes" in t or (t.endswith("notes") and "custom" not in t):
        return (
            f"SELECT TOP 50 EventTime, Message "
            f"FROM Orion.Events WHERE NetObjectID = {N} ORDER BY EventTime DESC",
            "NodeNotes missing — Events proxy",
            "table",
        )
    if "healthsummary" in f:
        return (
            f"SELECT Status, StatusDescription, CPULoad, PercentMemoryUsed "
            f"FROM Orion.Nodes WHERE NodeID = {N}",
            "health rollup guess (current node stats)",
            "table",
        )
    if "averageresptimepacketloss" in f or "response time & packet loss" in t or "network latency & packet loss" in t:
        return (
            f"SELECT DateTime, AvgResponseTime, PercentLoss "
            f"FROM Orion.ResponseTime WHERE NodeID = {N} ORDER BY DateTime",
            "Orion.ResponseTime history",
            "timeseries:ms",
        )
    if "cpumemoryradial" in f or "cpu load & memory utilization" in t or "cpu load & memory usage" in t:
        return (
            f"SELECT DateTime, AvgLoad, AvgPercentMemoryUsed "
            f"FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
            "Orion.CPULoad history",
            "timeseries:percent",
        )
    if "minmax avg cpuload" in n or "min/max/average cpu" in t or "min/max avg cpuload" in n:
        return (
            f"SELECT DateTime, AvgLoad, MaxLoad "
            f"FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
            "Orion.CPULoad min/max/avg history",
            "timeseries:percent",
        )
    if "linuxloadaverage" in f or "load average" in t:
        return (
            f"SELECT DateTime, AvgLoad FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
            "load average → Orion.CPULoad history",
            "timeseries:percent",
        )
    if "multipleobjectchart" in f:
        return (
            f"SELECT DateTime, AvgLoad, AvgPercentMemoryUsed "
            f"FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
            "multi-object chart → CPULoad history",
            "timeseries:percent",
        )
    if "capacityforecast" in f or "capacity forecast" in t:
        return (
            f"SELECT DateTime, AvgLoad, AvgPercentMemoryUsed "
            f"FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
            "capacity forecast → CPU/mem history",
            "timeseries:percent",
        )
    if "network utilization" in t or ("baselinechart" in f and "network" in t):
        return (
            f"SELECT DateTime, InAveragebps, OutAveragebps, InPercentUtil, OutPercentUtil "
            f"FROM Orion.NPM.InterfaceTraffic WHERE NodeID = {N} ORDER BY DateTime",
            "node interface traffic history (network util)",
            "timeseries:bps",
        )
    if "nodechart" in f:
        if "f5" in t or "power" in t or "energywise" in t:
            return (
                None,
                "F5/power NodeChart needs module-specific history entities not in this lab catalog",
                "markdown",
            )
        if "latency" in t or "packet loss" in t or "response time" in t:
            return (
                f"SELECT DateTime, AvgResponseTime, PercentLoss "
                f"FROM Orion.ResponseTime WHERE NodeID = {N} ORDER BY DateTime",
                "NodeChart → ResponseTime history",
                "timeseries:ms",
            )
        if "cpu" in t or "memory" in t or "load" in t:
            return (
                f"SELECT DateTime, AvgLoad, AvgPercentMemoryUsed "
                f"FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
                "NodeChart → CPULoad history",
                "timeseries:percent",
            )
        return (
            f"SELECT DateTime, AvgLoad, AvgPercentMemoryUsed "
            f"FROM Orion.CPULoad WHERE NodeID = {N} ORDER BY DateTime",
            "NodeChart generic → CPULoad history",
            "timeseries:percent",
        )
    if "percent disk" in t or "disk space used" in t:
        return (
            f"SELECT h.DateTime, h.PercentDiskUsed, v.Caption AS Volume "
            f"FROM Orion.VolumeUsageHistory h "
            f"JOIN Orion.Volumes v ON v.VolumeID = h.VolumeID "
            f"WHERE v.NodeID = {N} ORDER BY h.DateTime",
            "VolumeUsageHistory for node volumes",
            "timeseries:percent",
        )
    if "hardwarehealth" in f or "current hardware health" in t or t == "hardware health" or t == "hardware details":
        return (
            f"SELECT Name, Status, StatusDescription FROM Orion.HardwareHealth.HardwareInfo "
            f"WHERE NodeID = {N}",
            "HardwareHealth.HardwareInfo",
            "table",
        )
    if "listofnodevlans" in f or "vlans on node" in t:
        return (
            f"SELECT Caption, Name, Status FROM Orion.NPM.Interfaces WHERE NodeID = {N}",
            "NPM.VLANs missing — interfaces proxy",
            "table",
        )
    if "listofvrfs" in f or "vrfs on node" in t:
        return (
            f"SELECT Caption, Name, Status FROM Orion.NPM.Interfaces WHERE NodeID = {N}",
            "NPM.VRFs missing — interfaces proxy",
            "table",
        )
    if "neighbortable" in f or "routing neighbors" in t:
        return (
            NODE_STUB,
            "routing neighbors entity missing — node stub",
            "table",
        )
    if "routingtable" in f or "routing table" in t:
        return (
            NODE_STUB,
            "Orion.NodeRoutes missing — node stub",
            "table",
        )
    if "routingdetails" in f or "routing details" in t:
        return (
            NODE_STUB,
            "routing details stub",
            "table",
        )
    if "networktopology" in f:
        return (
            f"SELECT Status, StatusDescription, MachineType FROM Orion.Nodes WHERE NodeID = {N}",
            "L2 topology entity shape unknown — node stub",
            "table",
        )
    if "energywise" in f or "power consumption" in t:
        return (
            f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "EnergyWise entity often absent",
            "table",
        )
    if "multicast" in f or "multicast" in t:
        return (
            f"SELECT Caption, Status FROM Orion.NPM.Interfaces WHERE NodeID = {N}",
            "multicast → interfaces proxy",
            "table",
        )
    if "switchstack" in f or "stack data ring" in t or "stack power ring" in t:
        return (
            f"SELECT MachineType, Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "switch stack entities may be absent",
            "table",
        )

    # UDT / wireless / ports
    if "allaccesspointsfornode" in f or "access points and ssids" in t:
        return (
            f"SELECT Caption, Name, Status FROM Orion.NPM.Interfaces WHERE NodeID = {N}",
            "Wireless.AccessPoints missing — interfaces proxy",
            "table",
        )
    if "portscurrentlyinuse" in f or "ports currently in use" in t or "ethernet ports used" in t:
        return (
            f"SELECT Caption, Name, Status, InPercentUtil, OutPercentUtil "
            f"FROM Orion.NPM.Interfaces WHERE NodeID = {N}",
            "UDT.Port missing — interfaces proxy",
            "table",
        )
    if "portdetailslist" in f or t == "port details":
        return (
            f"SELECT Caption, Name, Status, FullName "
            f"FROM Orion.NPM.Interfaces WHERE NodeID = {N}",
            "UDT.Port missing — interfaces proxy",
            "table",
        )
    if "addcpollingdetails" in f or "domain controller" in t:
        return (
            f"SELECT MachineType, Vendor, Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "AD DC details → node stub",
            "table",
        )

    # APM / SAM
    if "/apm/" in f or "application" in t or "components by" in t or "monitored processes" in t:
        return (
            f"SELECT Name, Status, StatusDescription "
            f"FROM Orion.APM.Application WHERE NodeID = {N}",
            "APM.Application (+ process/component entities if licensed)",
            "table",
        )
    if "windowstaskscheduler" in f or "scheduled tasks" in t:
        return (
            f"SELECT ApplicationID, NodeID, Name, Status FROM Orion.APM.Application WHERE NodeID = {N}",
            "WSTM → applications proxy",
            "table",
        )
    if "appstack" in f:
        return (
            f"SELECT Name, Status FROM Orion.APM.Application WHERE NodeID = {N}",
            "AppStack → related applications",
            "table",
        )

    # NTA / NetFlow
    if "trafficanalysis" in f or "top xx applications" in t or "top xx conversations" in t or "top xx endpoints" in t:
        return (
            NODE_STUB,
            "NTA TopXX needs NetFlow entities; node stub if NTA absent",
            "table",
        )

    # NCM
    if "/ncm/" in f or "config list" in t or "config changes" in t or "policy violation" in t or "firmware vulnerabilit" in t or "ncm events" in t or t == "contexts":
        return (
            NODE_STUB,
            "NCM entities vary by version; node stub + see Configs tab notes",
            "table",
        )

    # VIM / cloud / storage
    if "/vim/" in f or "virtual machine" in t or "vmware" in t or "resource utilization" in t:
        return (
            f"SELECT MachineType, Vendor, Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "VIM details → node stub if VIM entities missing",
            "table",
        )
    if "cloudinstance" in f or "aws cloud" in t or "azure cloud" in t or "attached cloud" in t:
        return (
            f"SELECT MachineType, IP_Address, Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "cloud instance → node stub",
            "table",
        )
    if "vmanstorage" in f or ("storage" in t and "volume" not in t):
        return (
            f"SELECT Caption, VolumePercentUsed, VolumeSize, Status FROM Orion.Volumes WHERE NodeID = {N}",
            "storage tab → volumes proxy",
            "table",
        )

    # Asset Inventory
    if "assetinventory" in f:
        return (
            f"SELECT Vendor, MachineType, IOSVersion, Location, Contact, Description, Status, StatusDescription "
            f"FROM Orion.Nodes WHERE NodeID = {N}",
            "asset inventory entities → node/hardware stub",
            "table",
        )

    # WSUS / Patch
    if "/pm/" in f or "wsus" in t or "missing updates" in t or "installed updates" in t or "node updates" in t:
        return (
            f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "WSUS/PM entities may be absent",
            "table",
        )

    # F5 / SD-WAN / VDC / PCU / containers / custom query
    if "/f5/" in f or "sd-wan" in t or "vpn tunnel" in t or "edge device" in t or "warm spare" in t or "wan uplinks" in t:
        return (
            f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "vendor/SD-WAN resource → node stub",
            "table",
        )
    if "virtualdevicecontext" in f:
        return (
            NODE_STUB,
            "VDC stub",
            "table",
        )
    if "powercontrolunit" in f or "pcustatus" in f:
        return (
            f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "PCU stub",
            "table",
        )
    if "containers" in t or "application connections" in t or "api pollers" in t or "alertstack" in t:
        return (
            f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "XUI wrapper → node stub",
            "table",
        )
    if "customquery" in f:
        return (
            f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}",
            "CustomQuery resource — original SWQL unknown; node stub",
            "table",
        )

    # QoE / DPI
    if "dpi" in f or "quality of experience" in t:
        return (
            NODE_STUB,
            "DPI/QoE entities may be absent",
            "table",
        )

    # VNQM / VoIP
    if "/voip/" in f or "pri trunk" in t or "callmanager" in t or "call manager" in t or "mos" in t or ("jitter" in t and "sd-wan" not in t):
        return (
            NODE_STUB,
            "VNQM entities may be absent",
            "table",
        )

    # SEUM / WPM transactions
    if "/seum/" in f or "transaction" in t:
        return (
            NODE_STUB,
            "SEUM/WPM entities may be absent",
            "table",
        )

    # Server configuration / security empty tabs
    if "server configuration" in t or "bmc" in f:
        return (
            f"SELECT MachineType, Vendor, IOSImage, IOSVersion, Status, StatusDescription "
            f"FROM Orion.Nodes WHERE NodeID = {N}",
            "server/BMC config stub",
            "table",
        )

    # Default guess
    return (
        NODE_STUB,
        f"generic fallback for {title!r}",
        "table",
    )


def empty_tab_panels(tab_title: str) -> list[dict[str, str]]:
    """Synthetic widgets when Orion export had zero resources."""
    common = [
        {
            "resourceTitle": f"{tab_title} — export empty",
            "resourceName": "empty",
            "resourceFile": "",
            "viewColumn": 1,
            "position": 1,
            "markdown_force": (
                f"Orion view **{tab_title}** exported with **0 resources** "
                f"(module chrome / XUI / not in SWIS view metadata). "
                f"Panels below are best-effort SWQL guesses."
            ),
        }
    ]
    guesses = {
        "Access Lists": [
            ("Access Lists (guess)", NODE_STUB),
        ],
        "Policies": [
            ("Security Policies (guess)", NODE_STUB),
        ],
        "Policy Compliance": [
            ("Compliance Status (guess)", f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}"),
        ],
        "Map": [
            ("Maps (guess)", NODE_STUB),
        ],
        "Security Summary": [
            ("Node security stub", f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}"),
        ],
        "SEM Dashboard": [
            ("SEM stub", NODE_STUB),
        ],
        "Vulnerability and Risk Dashboard": [
            ("Vulnerability stub", f"SELECT Status, StatusDescription FROM Orion.Nodes WHERE NodeID = {N}"),
        ],
    }
    out = list(common)
    for i, (title, swql) in enumerate(guesses.get(tab_title, []), start=2):
        out.append(
            {
                "resourceTitle": title,
                "resourceName": title,
                "resourceFile": "",
                "viewColumn": 1,
                "position": i,
                "forced_swql": swql,
                "forced_note": "empty-tab synthetic guess",
            }
        )
    return out


def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s[:48] or "panel"


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


def table_panel(
    pid: int,
    title: str,
    swql: str,
    description: str,
    *,
    status_rows: list[dict[str, Any]],
) -> dict[str, Any]:
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
                        "defaults": {
                            "custom": {
                                "align": "auto",
                                "filterable": True,
                                "cellOptions": {"type": "auto"},
                            }
                        },
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
) -> dict[str, Any]:
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


def markdown_panel(pid: int, title: str, content: str) -> dict[str, Any]:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": "Orion widget without a SWQL data surface",
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


def stat_panel(
    pid: int,
    title: str,
    field: str,
    *,
    status_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    swql = f"SELECT {field} FROM Orion.Nodes WHERE NodeID = {N}"
    defaults: dict[str, Any] = {
        "thresholds": {
            "mode": "absolute",
            "steps": [{"color": "green", "value": None}],
        }
    }
    overrides: list[dict[str, Any]] = []
    if field == "Status" and status_rows:
        defaults["mappings"] = status_value_mappings(status_rows)
        defaults["color"] = {"mode": "thresholds"}
        # build thresholds from status colors for numeric status
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
                "spec": {
                    "queries": [sw_query(swql)],
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
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "background",
                        "graphMode": "none",
                        "justifyMode": "auto",
                        "textMode": "auto",
                    },
                    "fieldConfig": {
                        "defaults": defaults,
                        "overrides": overrides,
                    },
                },
            },
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


def tab_sort_key(t: dict[str, Any]) -> tuple:
    if t.get("viewTitle") == "Summary":
        return (0, 0, "Summary")
    return (t.get("viewGroupPosition") or 99, 1, t.get("viewTitle") or "")


def build_manifest(nodes: list[dict], inventory: list[dict], validation: dict[str, Any]) -> dict[str, Any]:
    if not nodes:
        raise SystemExit("No Orion.Nodes")
    status_rows = load_statusinfo()
    options = []
    current = None
    for n in nodes:
        nid = str(n["NodeID"])
        cap = str(n.get("Caption") or nid)
        opt = {"text": cap, "value": nid, "selected": False}
        options.append(opt)
        if current is None:
            current = opt
            opt["selected"] = True
    query_text = ",".join(f"{o['text']} : {o['value']}" for o in options)

    elements: dict[str, Any] = {}
    tabs: list[dict[str, Any]] = []
    pid = 1
    report_rows: list[dict[str, Any]] = []

    for tab in sorted(inventory, key=tab_sort_key):
        title = tab["viewTitle"]
        resources = list(tab.get("resources") or [])
        if not resources:
            resources = empty_tab_panels(title)

        items: list[dict[str, Any]] = []
        col_y = {1: 0, 2: 0, 3: 0}

        # Summary header stats
        if title == "Summary":
            for st_title, field, x in [
                ("CPU Load %", "CPULoad", 0),
                ("Memory Used %", "PercentMemoryUsed", 4),
                ("Response Time", "ResponseTime", 8),
                ("Packet Loss %", "PercentLoss", 12),
                ("Status", "Status", 16),
            ]:
                el_name = f"panel-{pid}"
                elements[el_name] = stat_panel(
                    pid, st_title, field, status_rows=status_rows
                )
                items.append(grid_item(x, 0, 4 if x < 16 else 8, 4, el_name))
                pid += 1
            col_y = {1: 4, 2: 4, 3: 4}

        for r in resources:
            rtitle = r.get("resourceTitle") or r.get("resourceName") or f"widget-{pid}"
            rname = r.get("resourceName") or ""
            rfile = r.get("resourceFile") or ""
            col = int(r.get("viewColumn") or 1)
            if col not in (1, 2, 3):
                col = 1
            x = {1: 0, 2: 12, 3: 0}[col]
            w = 12

            if r.get("markdown_force"):
                el_name = f"panel-{pid}"
                elements[el_name] = markdown_panel(pid, rtitle, r["markdown_force"])
                h = 4
                items.append(grid_item(x, col_y[col], w, h, el_name))
                col_y[col] += h
                pid += 1
                report_rows.append({"tab": title, "title": rtitle, "kind": "markdown", "ok": True})
                continue

            if r.get("forced_swql"):
                swql, note, viz = r["forced_swql"], r.get("forced_note") or "synthetic", r.get("forced_viz") or "table"
            else:
                swql, note, viz = guess_swql(rtitle, rname, rfile)

            el_name = f"panel-{pid}"
            if swql is None or viz == "markdown":
                content = (
                    f"**{rtitle}**" + chr(10) + chr(10) + note + chr(10) + chr(10)
                    + f"- Orion file: `{rfile}`" + chr(10)
                    + f"- Open in Orion: [Node Details](http://3.88.155.134:8787/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N%3A${{node_id}})"
                )
                elements[el_name] = markdown_panel(pid, rtitle, content)
                h = 5
                kind = "markdown"
                ok = True
                err = None
            elif viz.startswith("timeseries"):
                unit = viz.split(":", 1)[1] if ":" in viz else ""
                desc = f"Orion history · {note}"
                elements[el_name] = timeseries_panel(
                    pid, rtitle, swql, desc, unit=unit
                )
                h = 10
                kind = "timeseries"
                ok = True
                err = None
            else:
                # substitute for validation lookup key
                val_key = swql
                v = validation.get(val_key) or {}
                status = v.get("status", "untested")
                err = v.get("error")
                rows = v.get("rows")
                if status == "error":
                    note = f"{note} · original SWQL failed SWIS ({err}); using node stub"
                    swql = NODE_STUB
                    status = "fallback"
                    err = None
                desc = (
                    f"Orion guess · {note} · SWIS:{status}"
                    + (f" rows={rows}" if rows is not None else "")
                    + (f" · {err}" if err else "")
                )
                elements[el_name] = table_panel(
                    pid, rtitle, swql, desc, status_rows=status_rows
                )
                h = 8
                kind = "table"
                ok = status in {"ok", "empty", "untested", "fallback"}

            items.append(grid_item(x, col_y[col], w, h, el_name))
            col_y[col] += h
            pid += 1
            report_rows.append(
                {
                    "tab": title,
                    "title": rtitle,
                    "kind": kind,
                    "ok": ok,
                    "note": note,
                    "file": rfile,
                    "error": err,
                }
            )

        tabs.append(
            {
                "kind": "TabsLayoutTab",
                "spec": {
                    "title": title,
                    "layout": {"kind": "GridLayout", "spec": {"items": items}},
                },
            }
        )

    manifest = {
        "kind": "Dashboard",
        "apiVersion": "dashboard.grafana.app/v2",
        "metadata": {
            "name": DASH_UID,
            "annotations": {
                "grafana.app/folder": FOLDER_UID,
                "grafana.app/message": "Full Orion Node Details clone with tabs + SWQL guesses",
            },
        },
        "spec": {
            "title": DASH_TITLE,
            "description": (
                "Clone of Orion Node Details view group — one Grafana tab per Orion subview, "
                "panel per classic widget (best-effort SWQL). Datasource AWS-SolarWinds "
                f"({DS_UID}). Variable $node_id."
            ),
            "tags": ["solarwinds", "clone", "node-details", "network-o11y", "tabs"],
            "editable": True,
            "preload": False,
            "liveNow": False,
            "cursorSync": "Crosshair",
            "links": [
                {
                    "title": "Orion Node Details",
                    "type": "link",
                    "icon": "external link",
                    "tooltip": "",
                    "url": "http://3.88.155.134:8787/Orion/NetPerfMon/NodeDetails.aspx?NetObject=N%3A${node_id}",
                    "tags": [],
                    "asDropdown": False,
                    "targetBlank": True,
                    "includeVars": False,
                    "keepTime": False,
                },
                *dashboard_nav_links(DASH_UID),
            ],
            "annotations": [],
            "variables": [
                {
                    "kind": "CustomVariable",
                    "spec": {
                        "name": "node_id",
                        "label": "Node",
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
    return manifest, report_rows


def validate_swqls(sw_env: dict[str, str], inventory: list[dict]) -> dict[str, Any]:
    """Dedupe SWQL guesses and validate against SWIS with node_id=1."""
    cache: dict[str, Any] = {}
    uniq: dict[str, str] = {}  # template -> concrete

    def consider(swql: str | None) -> None:
        if not swql:
            return
        concrete = swql.replace("$node_id", "1").replace("${node_id}", "1")
        uniq[swql] = concrete

    for tab in inventory:
        resources = tab.get("resources") or empty_tab_panels(tab["viewTitle"])
        for r in resources:
            if r.get("markdown_force"):
                continue
            if r.get("forced_swql"):
                consider(r["forced_swql"])
                continue
            swql, _, _ = guess_swql(
                r.get("resourceTitle") or "",
                r.get("resourceName") or "",
                r.get("resourceFile") or "",
            )
            consider(swql)

    print(f"Validating {len(uniq)} unique SWQL guesses against SWIS…")
    for i, (tmpl, concrete) in enumerate(sorted(uniq.items(), key=lambda x: x[0]), 1):
        rows, err = swis_query(sw_env, concrete)
        if err:
            # try TOP 1 simpler sometimes fails on complex — mark error
            cache[tmpl] = {"status": "error", "error": err, "rows": 0}
            print(f"  [{i}/{len(uniq)}] ERROR: {err[:80]}")
        else:
            n = len(rows or [])
            cache[tmpl] = {"status": "empty" if n == 0 else "ok", "error": None, "rows": n}
            print(f"  [{i}/{len(uniq)}] {cache[tmpl]['status']} rows={n}")
    return cache


def main() -> int:
    if not INVENTORY.exists():
        raise SystemExit(f"Missing inventory {INVENTORY} — run tmp-inventory-node-details.py first")
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    sw_env = load_env_file(ROOT / "swis.env")
    nodes, err = swis_query(sw_env, "SELECT NodeID, Caption FROM Orion.Nodes ORDER BY Caption")
    if err or nodes is None:
        raise SystemExit(f"Cannot list nodes: {err}")

    validation = validate_swqls(sw_env, inventory)
    val_path = ROOT / "out" / "latest" / "docs" / "node-details-swql-validation.json"
    val_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")

    manifest, report = build_manifest(nodes, inventory, validation)
    out = ROOT / "out" / "latest" / "grafana" / f"{DASH_UID}.v2.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report_path = ROOT / "out" / "latest" / "docs" / "node-details-panel-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    n_tabs = len(manifest["spec"]["layout"]["spec"]["tabs"])
    n_panels = len(manifest["spec"]["elements"])
    print(f"Wrote {out} tabs={n_tabs} panels={n_panels}")

    base, token = grafana_creds()
    # GET existing for resourceVersion / deprecatedInternalID
    get_path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{DASH_UID}"
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
        print(f"PUT HTTP {status} generation={resp.get('metadata', {}).get('generation')}")
    else:
        status, resp = api(
            "POST",
            f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards",
            token,
            base,
            manifest,
        )
        print(f"POST HTTP {status}")

    layout_kind = (resp.get("spec") or {}).get("layout", {}).get("kind")
    print(f"layout.kind={layout_kind} (expect TabsLayout)")
    print(f"Open: {base}/d/{DASH_UID}/")
    print(f"Report: {report_path}")
    return 0 if layout_kind == "TabsLayout" else 1


if __name__ == "__main__":
    raise SystemExit(main())
