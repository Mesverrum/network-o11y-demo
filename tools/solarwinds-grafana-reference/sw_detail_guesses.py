"""SWQL guesses for Orion detail-view clones. Returns (swql|None, note, viz).

viz is one of: table | markdown | timeseries[:unit]
"""
from __future__ import annotations

I = "$interface_id"
V = "$volume_id"
A = "$application_id"
C = "$component_id"
AL = "$alert_active_id"

__all__ = [
    "I",
    "V",
    "A",
    "C",
    "AL",
    "guess_interface",
    "guess_volume",
    "guess_application",
    "guess_component",
    "guess_alert",
]


def guess_interface(title: str, name: str, file: str) -> tuple[str | None, str, str]:
    t, f = (title or "").lower(), (file or "").replace("\\", "/").lower()
    if "management" in f or t == "management":
        return None, "Orion UI action widget", "markdown"
    if "interfacedetails" in f or t == "interface details":
        return (
            f"SELECT i.InterfaceID, i.NodeID, i.Caption, i.Name, i.FullName, i.InterfaceAlias, i.PhysicalAddress, "
            f"i.Status, i.StatusDescription, i.InterfaceTypeDescription, "
            f"i.Speed, i.MTU, i.InBandwidth, i.OutBandwidth, "
            f"i.InPercentUtil, i.OutPercentUtil, i.Inbps, i.Outbps, "
            f"i.InErrorsThisHour, i.OutErrorsThisHour, i.InDiscardsThisHour, i.OutDiscardsThisHour, "
            f"i.MaxInBpsToday, i.MaxOutBpsToday, n.Caption AS Node "
            f"FROM Orion.NPM.Interfaces i JOIN Orion.Nodes n ON n.NodeID = i.NodeID "
            f"WHERE i.InterfaceID = {I}",
            "interface details (validated fields)",
            "table",
        )
    if "polling" in t or "pollingdetails" in f:
        return (
            f"SELECT PollInterval, StatCollection, RediscoveryInterval, NextPoll, LastSync "
            f"FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}",
            "interface polling",
            "table",
        )
    if "config" in t and "custom" not in t:
        return (
            f"SELECT Caption, Name, FullName, InterfaceAlias, InterfaceTypeDescription, "
            f"Speed, MTU, InBandwidth, OutBandwidth, AdminStatus, OperStatus, PhysicalAddress "
            f"FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}",
            "interface config",
            "table",
        )
    if "event" in t:
        return (
            f"SELECT TOP 50 EventTime, Message, EventType FROM Orion.Events "
            f"WHERE NetObjectID = {I} ORDER BY EventTime DESC",
            "events",
            "table",
        )
    if "custom properties" in t:
        return (
            f"SELECT Caption, Status, StatusDescription, InterfaceAlias "
            f"FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}",
            "custom props stub",
            "table",
        )
    if "bits per second" in t:
        return (
            f"SELECT DateTime, InAveragebps, OutAveragebps, InMaxbps, OutMaxbps "
            f"FROM Orion.NPM.InterfaceTraffic WHERE InterfaceID = {I} ORDER BY DateTime",
            "Orion.NPM.InterfaceTraffic bps history",
            "timeseries:bps",
        )
    if ("utilization" in t and "percent" in t) or "real time" in t:
        return (
            f"SELECT DateTime, InPercentUtil, OutPercentUtil "
            f"FROM Orion.NPM.InterfaceTraffic WHERE InterfaceID = {I} ORDER BY DateTime",
            "Orion.NPM.InterfaceTraffic util history",
            "timeseries:percent",
        )
    if "errors and discards" in t or ("errors" in t and "discards" in t):
        return (
            f"SELECT DateTime, InErrors, OutErrors, InDiscards, OutDiscards "
            f"FROM Orion.NPM.InterfaceErrors WHERE InterfaceID = {I} ORDER BY DateTime",
            "Orion.NPM.InterfaceErrors history",
            "timeseries:short",
        )
    if "downtime" in t:
        return (
            f"SELECT DateTime, InPercentUtil, OutPercentUtil "
            f"FROM Orion.NPM.InterfaceTraffic WHERE InterfaceID = {I} ORDER BY DateTime",
            "downtime → util history proxy",
            "timeseries:percent",
        )
    if "dependencies" in t:
        return ("SELECT ParentUri, ChildUri FROM Orion.Dependencies", "dependencies list", "table")
    if "top xx" in t or "trafficanalysis" in f:
        return (
            f"SELECT DateTime, InAveragebps, OutAveragebps "
            f"FROM Orion.NPM.InterfaceTraffic WHERE InterfaceID = {I} ORDER BY DateTime",
            "NTA stub → traffic history",
            "timeseries:bps",
        )
    if "energywise" in f or "fibre" in t or "vsan" in t or "power" in t or "alertstack" in t:
        return (
            f"SELECT Caption, Status, StatusDescription, InPercentUtil, OutPercentUtil, Inbps, Outbps "
            f"FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}",
            "module stub → current interface stats",
            "table",
        )
    return (
        f"SELECT Caption, Status, StatusDescription, InPercentUtil, OutPercentUtil, Inbps, Outbps "
        f"FROM Orion.NPM.Interfaces WHERE InterfaceID = {I}",
        f"generic interface fallback for {title!r}",
        "table",
    )


def guess_volume(title: str, name: str, file: str) -> tuple[str | None, str, str]:
    t, f = (title or "").lower(), (file or "").replace("\\", "/").lower()
    if "management" in f or t == "management":
        return None, "Orion UI action widget", "markdown"
    if t == "volume details" or "volumedetails" in f:
        return (
            f"SELECT v.VolumeID, v.NodeID, v.Caption, v.FullName, v.VolumeDescription, v.VolumeType, v.Status, v.StatusDescription, "
            f"v.VolumePercentUsed, v.VolumeSize, v.VolumeSpaceUsed, v.VolumeSpaceAvailable, "
            f"v.TotalDiskIOPS, v.VolumeResponding, n.Caption AS Node "
            f"FROM Orion.Volumes v JOIN Orion.Nodes n ON n.NodeID = v.NodeID WHERE v.VolumeID = {V}",
            "volume details (validated fields)",
            "table",
        )
    if "polling" in t:
        return (
            f"SELECT Caption, Status, NextPoll, LastSync, VolumeResponding "
            f"FROM Orion.Volumes WHERE VolumeID = {V}",
            "volume polling",
            "table",
        )
    if "alert" in t:
        return (
            f"SELECT aa.AlertActiveID, o.RelatedNodeId, a.Name AS AlertName, aa.TriggeredMessage, aa.TriggeredDateTime, o.EntityCaption FROM Orion.AlertActive aa JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID JOIN Orion.Volumes v ON v.NodeID = o.RelatedNodeId "
            f"WHERE v.VolumeID = {V} ORDER BY aa.TriggeredDateTime DESC",
            "alerts on volume's node",
            "table",
        )
    if (
        "percent disk" in t
        or "average disk space" in t
        or "volume size" in t
        or "capacity forecast" in t
        or "storage capacity" in t
    ):
        return (
            f"SELECT DateTime, PercentDiskUsed, AvgDiskUsed, DiskSize "
            f"FROM Orion.VolumeUsageHistory WHERE VolumeID = {V} ORDER BY DateTime",
            "Orion.VolumeUsageHistory",
            "timeseries:percent",
        )
    if "iops" in t or "queue" in t or "transfer" in t or "disk sec" in t:
        return (
            f"SELECT DateTime, AvgDiskQueueLength, AvgDiskReads, AvgDiskWrites, AvgDiskTransfer "
            f"FROM Orion.VolumePerformanceHistory WHERE VolumeID = {V} ORDER BY DateTime",
            "Orion.VolumePerformanceHistory",
            "timeseries:short",
        )
    if "appstack" in f or "virtualization" in t or "network storage" in t:
        return (
            f"SELECT Caption, VolumeType, Status, StatusDescription, VolumePercentUsed, TotalDiskIOPS "
            f"FROM Orion.Volumes WHERE VolumeID = {V}",
            "module stub",
            "table",
        )
    return (
        f"SELECT Caption, Status, StatusDescription, VolumePercentUsed, VolumeSize, TotalDiskIOPS "
        f"FROM Orion.Volumes WHERE VolumeID = {V}",
        f"generic volume fallback for {title!r}",
        "table",
    )


def guess_application(title: str, name: str, file: str) -> tuple[str | None, str, str]:
    t, f = (title or "").lower(), (file or "").replace("\\", "/").lower()
    if "management" in f or t == "management":
        return None, "Orion UI action widget", "markdown"
    if t == "application details" or ("details" in t and "component" not in t and "custom" not in t):
        return (
            f"SELECT a.ApplicationID, a.NodeID, a.Name, a.Status, a.StatusDescription, a.DetailsUrl, n.Caption AS Node FROM Orion.APM.Application a JOIN Orion.Nodes n ON n.NodeID = a.NodeID "
            f"WHERE a.ApplicationID = {A}",
            "application details",
            "table",
        )
    if "component" in t or "process" in t or "service" in t:
        return (
            f"SELECT ComponentID, ApplicationID, Name, Status FROM Orion.APM.Component WHERE ApplicationID = {A} ORDER BY Name",
            "components for application",
            "table",
        )
    if "alert" in t:
        return (
            f"SELECT aa.AlertActiveID, o.RelatedNodeId, al.Name AS AlertName, aa.TriggeredMessage, aa.TriggeredDateTime, o.EntityCaption FROM Orion.AlertActive aa JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID JOIN Orion.AlertConfigurations al ON al.AlertID = o.AlertID JOIN Orion.APM.Application app ON app.NodeID = o.RelatedNodeId "
            f"WHERE app.ApplicationID = {A} ORDER BY aa.TriggeredDateTime DESC",
            "alerts on application node",
            "table",
        )
    if "event" in t:
        return (
            f"SELECT TOP 50 EventTime, Message, EventType FROM Orion.Events "
            f"WHERE NetObjectID = {A} ORDER BY EventTime DESC",
            "application events",
            "table",
        )
    if "cpu" in t or "memory" in t or "availability" in t:
        return (
            f"SELECT c.DateTime, c.AvgLoad, c.AvgPercentMemoryUsed "
            f"FROM Orion.CPULoad c "
            f"JOIN Orion.APM.Application a ON a.NodeID = c.NodeID "
            f"WHERE a.ApplicationID = {A} ORDER BY c.DateTime",
            "host CPU/memory history via application node",
            "timeseries:percent",
        )
    if t == "summary" or "custom" in t or "connection" in t or "appstack" in f:
        return (
            f"SELECT Name, Status, StatusDescription FROM Orion.APM.Application WHERE ApplicationID = {A}",
            "application status snapshot",
            "table",
        )
    return (
        f"SELECT Name, Status, StatusDescription FROM Orion.APM.Application WHERE ApplicationID = {A}",
        f"generic application fallback for {title!r}",
        "table",
    )


def guess_component(title: str, name: str, file: str) -> tuple[str | None, str, str]:
    t, f = (title or "").lower(), (file or "").replace("\\", "/").lower()
    if "management" in f:
        return None, "Orion UI action widget", "markdown"
    if "component details" in t or "monitordetails" in f:
        return (
            f"SELECT c.ComponentID, c.ApplicationID, a.NodeID, c.Name, c.Status, a.Name AS Application FROM Orion.APM.Component c JOIN Orion.APM.Application a ON a.ApplicationID = c.ApplicationID "
            f"WHERE c.ComponentID = {C}",
            "component + parent application (catalog fields)",
            "table",
        )
    if "settings" in t or "statistic" in t or "gauge" in f or "availability" in t:
        return (
            f"SELECT Name, Status FROM Orion.APM.Component WHERE ComponentID = {C}",
            "component catalog fields only",
            "table",
        )
    if "cpu" in t or "memory" in t:
        return (
            f"SELECT cl.DateTime, cl.AvgLoad, cl.AvgPercentMemoryUsed "
            f"FROM Orion.CPULoad cl "
            f"JOIN Orion.APM.Application a ON a.NodeID = cl.NodeID "
            f"JOIN Orion.APM.Component c ON c.ApplicationID = a.ApplicationID "
            f"WHERE c.ComponentID = {C} ORDER BY cl.DateTime",
            "host CPU/mem history for component application node",
            "timeseries:percent",
        )
    if "response time" in t:
        return (
            f"SELECT rt.DateTime, rt.AvgResponseTime, rt.PercentLoss "
            f"FROM Orion.ResponseTime rt "
            f"JOIN Orion.APM.Application a ON a.NodeID = rt.NodeID "
            f"JOIN Orion.APM.Component c ON c.ApplicationID = a.ApplicationID "
            f"WHERE c.ComponentID = {C} ORDER BY rt.DateTime",
            "host response-time history for component application node",
            "timeseries:ms",
        )
    if "i/o" in t or "chart" in t:
        return (
            f"SELECT Name, Status FROM Orion.APM.Component WHERE ComponentID = {C}",
            "no APM component history entity — status snapshot",
            "table",
        )
    if "event" in t or "log" in t:
        return (
            f"SELECT TOP 25 EventTime, Message, EventType FROM Orion.Events "
            f"WHERE NetObjectID = {C} ORDER BY EventTime DESC",
            "component events",
            "table",
        )
    return (
        f"SELECT Name, Status FROM Orion.APM.Component WHERE ComponentID = {C}",
        f"generic component fallback for {title!r}",
        "table",
    )


def guess_alert(title: str, name: str, file: str) -> tuple[str | None, str, str]:
    t, f = (title or "").lower(), (file or "").replace("\\", "/").lower()
    if "management" in f or t == "management":
        return None, "Orion UI action widget", "markdown"
    if "definition" in t:
        return (
            f"SELECT a.Name, a.Description, a.Severity, a.Enabled, a.ObjectType "
            f"FROM Orion.AlertActive aa "
            f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            f"JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
            f"WHERE aa.AlertActiveID = {AL}",
            "alert definition",
            "table",
        )
    if "status overview" in t or "alert status" in t:
        return (
            f"SELECT aa.AlertActiveID, o.RelatedNodeId, a.Name AS AlertName, aa.TriggeredMessage, aa.TriggeredDateTime, aa.Acknowledged, aa.AcknowledgedBy, aa.AcknowledgedDateTime, o.EntityCaption, o.EntityDetailsUrl FROM Orion.AlertActive aa "
            f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            f"JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
            f"WHERE aa.AlertActiveID = {AL}",
            "active alert overview",
            "table",
        )
    if "history" in t:
        return (
            f"SELECT TOP 50 aa.TriggeredDateTime, a.Name AS AlertName, o.EntityCaption, aa.TriggeredMessage "
            f"FROM Orion.AlertActive aa "
            f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            f"JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
            f"JOIN Orion.AlertActive cur ON cur.AlertActiveID = {AL} "
            f"JOIN Orion.AlertObjects curo ON curo.AlertObjectID = cur.AlertObjectID "
            f"WHERE o.AlertID = curo.AlertID ORDER BY aa.TriggeredDateTime DESC",
            "history of this alert definition",
            "table",
        )
    if "other objects" in t:
        return (
            f"SELECT a.Name AS AlertName, aa.TriggeredDateTime, o.EntityCaption, aa.TriggeredMessage "
            f"FROM Orion.AlertActive aa "
            f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            f"JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
            f"JOIN Orion.AlertActive cur ON cur.AlertActiveID = {AL} "
            f"JOIN Orion.AlertObjects curo ON curo.AlertObjectID = cur.AlertObjectID "
            f"WHERE o.AlertID = curo.AlertID AND aa.AlertActiveID <> {AL} "
            f"ORDER BY aa.TriggeredDateTime DESC",
            "other objects with same alert",
            "table",
        )
    if "top 10" in t or "trigger count" in t:
        return (
            f"SELECT TOP 10 o.EntityCaption, COUNT(aa.AlertActiveID) AS TriggerCount "
            f"FROM Orion.AlertActive aa "
            f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            f"JOIN Orion.AlertActive cur ON cur.AlertActiveID = {AL} "
            f"JOIN Orion.AlertObjects curo ON curo.AlertObjectID = cur.AlertObjectID "
            f"WHERE o.AlertID = curo.AlertID "
            f"GROUP BY o.EntityCaption ORDER BY TriggerCount DESC",
            "top objects by trigger count",
            "table",
        )
    if "notes" in t:
        return (
            f"SELECT a.Name AS AlertName, aa.TriggeredMessage, aa.TriggeredDateTime "
            f"FROM Orion.AlertActive aa "
            f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
            f"JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
            f"WHERE aa.AlertActiveID = {AL}",
            "alert notes stub",
            "table",
        )
    if "related node" in t:
        return (
            f"SELECT n.NodeID, o.RelatedNodeId, aa.AlertActiveID, n.Caption AS Node, n.Status, n.StatusDescription, n.CPULoad, n.PercentMemoryUsed FROM Orion.AlertActive aa JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID JOIN Orion.Nodes n ON n.NodeID = o.RelatedNodeId "
            f"WHERE aa.AlertActiveID = {AL}",
            "related node status",
            "table",
        )
    if (
        "xuiwrapper" in f
        or "requester" in t
        or "perfstack" in t
        or "service incident" in t
        or "integration" in t
        or "recommendation" in t
        or "triggered by event" in t
        or "alertstack" in t
        or "ip address request" in t
    ):
        return None, "Orion UI / integration chrome — no reliable SWQL", "markdown"
    return (
        f"SELECT a.Name AS AlertName, aa.TriggeredMessage, aa.TriggeredDateTime, o.EntityCaption "
        f"FROM Orion.AlertActive aa "
        f"JOIN Orion.AlertObjects o ON o.AlertObjectID = aa.AlertObjectID "
        f"JOIN Orion.AlertConfigurations a ON a.AlertID = o.AlertID "
        f"WHERE aa.AlertActiveID = {AL}",
        f"generic alert fallback for {title!r}",
        "table",
    )
