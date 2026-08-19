"""Shared SolarWinds clone dashboard UIDs, nav links, and scoped table data-links."""
from __future__ import annotations

import re
from typing import Any, Iterable

DASH = {
    "top10": "sw-current-top-10-lists",
    "network_top10": "sw-network-top-10",
    "npm_summary": "sw-npm-summary",
    "app_summary": "sw-application-summary",
    "node": "sw-node-details-summary",
    "interface": "sw-interface-details",
    "volume": "sw-volume-details",
    "application": "sw-application-details",
    "component": "sw-component-details",
    "alert": "sw-alert-details",
}

NAV_ORDER: list[tuple[str, str]] = [
    ("npm_summary", "NPM Summary"),
    ("network_top10", "Network Top 10"),
    ("top10", "Current Top 10"),
    ("app_summary", "Application Summary"),
    ("node", "Node Details"),
    ("interface", "Interface Details"),
    ("volume", "Volume Details"),
    ("application", "Application Details"),
    ("component", "Component Details"),
    ("alert", "Alert Details"),
]

LINK_ID_FIELDS = frozenset(
    {
        "NodeID",
        "InterfaceID",
        "VolumeID",
        "ApplicationID",
        "ComponentID",
        "AlertActiveID",
        "RelatedNodeId",
    }
)

# Panel link profiles — only these entity drills appear on a given table
Kind = str  # node|interface|volume|application|component|alert


def data_link(title: str, uid: str, var: str, field: str) -> dict[str, Any]:
    """Drill to detail board. Use bracket field ref; keep URL simple for reliable var sync."""
    return {
        "title": title,
        "url": f"/d/{uid}?var-{var}=${{__data.fields[\"{field}\"]}}",
        "targetBlank": False,
    }


def value_link(title: str, uid: str, var: str) -> dict[str, Any]:
    """Link when the clicked cell *is* the ID field."""
    return {
        "title": title,
        "url": f"/d/{uid}?var-{var}=${{__value.raw}}",
        "targetBlank": False,
    }


def dashboard_nav_links(current_uid: str | None = None) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for key, label in NAV_ORDER:
        uid = DASH[key]
        if current_uid and uid == current_uid:
            continue
        links.append(
            {
                "title": label,
                "type": "link",
                "icon": "dashboard",
                "tooltip": f"Open {label}",
                "url": f"/d/{uid}",
                "tags": [],
                "asDropdown": False,
                "targetBlank": False,
                "includeVars": False,
                "keepTime": True,
            }
        )
    return links


def infer_link_kinds(swql: str | None, title: str = "") -> set[Kind]:
    """Infer which detail drills belong on this panel from SWQL + title."""
    s = (swql or "").lower()
    t = (title or "").lower()
    kinds: set[Kind] = set()

    if "npm.interfaces" in s or "interfaceid" in s or "interface" in t:
        kinds.add("interface")
    if "orion.volumes" in s or "volumeusagehistory" in s or "volumeid" in s or "volume" in t:
        kinds.add("volume")
    if "apm.application" in s or "applicationid" in s or "application" in t:
        kinds.add("application")
    if "apm.component" in s or "componentid" in s or "component" in t:
        kinds.add("component")
    if "alertactive" in s or "alertactiveid" in s or "alert" in t:
        kinds.add("alert")
    if (
        "orion.nodes" in s
        or re.search(r"\bnodeid\b", s)
        or "node" in t
        or "cpu" in t
        or "memory" in t
        or "response time" in t
        or "packet loss" in t
    ):
        kinds.add("node")

    # Joins often include Nodes for Caption AS Node — keep node drill when NodeID present
    if "nodeid" in s.replace(" ", ""):
        kinds.add("node")

    # Top-XX interface tables should not also offer volume/app just because of loose title match
    if kinds & {"interface"} and "volume" not in t and "application" not in t:
        kinds.discard("volume")
        kinds.discard("application")
        kinds.discard("component")
        kinds.discard("alert")
    if kinds & {"volume"} and "interface" not in t and "application" not in t:
        kinds.discard("interface")
        kinds.discard("application")
        kinds.discard("component")
        kinds.discard("alert")
    if kinds & {"application", "component"} and "interface" not in t:
        kinds.discard("interface")
        kinds.discard("volume")
    if kinds == {"alert"} or (kinds & {"alert"} and "interface" not in t):
        kinds.discard("interface")
        kinds.discard("volume")
        kinds.discard("application")
        kinds.discard("component")

    if not kinds:
        kinds.add("node")
    return kinds


def _override(field: str, links: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "matcher": {"id": "byName", "options": field},
        "properties": [{"id": "links", "value": links}],
    }


def entity_data_link_overrides(kinds: Iterable[Kind] | None = None) -> list[dict[str, Any]]:
    """Only emit drills for requested entity kinds (no Caption→everything)."""
    k = set(kinds or ("node", "interface", "volume", "application", "component", "alert"))
    out: list[dict[str, Any]] = []

    node = [data_link("Node Details", DASH["node"], "node_id", "NodeID")]
    node_rel = [data_link("Node Details", DASH["node"], "node_id", "RelatedNodeId")]
    iface = [data_link("Interface Details", DASH["interface"], "interface_id", "InterfaceID")]
    vol = [data_link("Volume Details", DASH["volume"], "volume_id", "VolumeID")]
    app = [data_link("Application Details", DASH["application"], "application_id", "ApplicationID")]
    comp = [data_link("Component Details", DASH["component"], "component_id", "ComponentID")]
    alert = [data_link("Alert Details", DASH["alert"], "alert_active_id", "AlertActiveID")]

    if "node" in k:
        out.append(_override("Node", node))
        out.append(_override("NodeName", node))
        out.append(_override("SysName", node))
        # Node tables use Caption as the hostname
        if "interface" not in k and "volume" not in k and "application" not in k:
            out.append(_override("Caption", node))
        out.append(_override("NodeID", [value_link("Node Details", DASH["node"], "node_id")]))

    if "interface" in k:
        out.append(_override("Interface", iface))
        out.append(_override("FullName", iface))
        # Interface-only tables may still SELECT Caption
        if "volume" not in k and "application" not in k and "node" not in k:
            out.append(_override("Caption", iface))
        elif "node" in k and "volume" not in k and "application" not in k:
            # iface + parent node: Caption is usually the interface name when not aliased
            out.append(_override("Caption", iface))
        out.append(
            _override("InterfaceID", [value_link("Interface Details", DASH["interface"], "interface_id")])
        )

    if "volume" in k:
        out.append(_override("Volume", vol))
        if "interface" not in k and "application" not in k:
            out.append(_override("Caption", vol))
        out.append(_override("VolumeID", [value_link("Volume Details", DASH["volume"], "volume_id")]))

    if "application" in k:
        out.append(_override("Application", app))
        out.append(_override("Template", app))
        if "component" not in k:
            out.append(_override("Name", app))
        out.append(
            _override(
                "ApplicationID",
                [value_link("Application Details", DASH["application"], "application_id")],
            )
        )

    if "component" in k:
        out.append(_override("Component", comp))
        out.append(_override("Name", comp + (app if "application" in k else [])))
        out.append(
            _override(
                "ComponentID",
                [value_link("Component Details", DASH["component"], "component_id")],
            )
        )

    if "alert" in k:
        out.append(_override("AlertName", alert))
        out.append(_override("TriggeredMessage", alert))
        out.append(_override("EntityCaption", alert + (node_rel if "node" in k or True else [])))
        out.append(
            _override("AlertActiveID", [value_link("Alert Details", DASH["alert"], "alert_active_id")])
        )
        out.append(_override("RelatedNodeId", [value_link("Node Details", DASH["node"], "node_id")]))

    return out


def hide_id_overrides() -> list[dict[str, Any]]:
    """Hide ID columns in the table UI but keep them in the frame for data links.

    Must be field override (Hide in table), NEVER organize-exclude — excluded fields
    cannot be referenced by ${__data.fields.*}.
    """
    return [
        {
            "matcher": {"id": "byName", "options": name},
            "properties": [{"id": "custom.hidden", "value": True}],
        }
        for name in sorted(LINK_ID_FIELDS)
    ]


def merge_table_overrides(
    status_hide_overrides: list[dict[str, Any]],
    *,
    swql: str | None = None,
    title: str = "",
    kinds: Iterable[Kind] | None = None,
) -> list[dict[str, Any]]:
    resolved = set(kinds) if kinds is not None else infer_link_kinds(swql, title)
    # Drop generic Status hide-by-regexp ID hide if present — we use explicit hide_id_overrides
    cleaned = [
        o
        for o in status_hide_overrides
        if not (
            (o.get("matcher") or {}).get("id") == "byRegexp"
            and "NodeID" in str((o.get("matcher") or {}).get("options") or "")
        )
    ]
    return cleaned + hide_id_overrides() + entity_data_link_overrides(resolved)
