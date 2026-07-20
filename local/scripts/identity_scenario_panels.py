#!/usr/bin/env python3
"""Identity-scenario panels for lab-network-join-demo (OTel entity open questions)."""
from __future__ import annotations

# Hardcode Prom UID — ${datasource} is fine elsewhere, but identity panels were
# showing No data for some clients; pin to the known GC Prometheus uid.
DS = {"type": "prometheus", "uid": "grafanacloud-prom"}
# Filter only on demo_model. Do NOT also require tester_id — that compound
# matcher was a common "No data" footgun when the variable lagged refresh.
MODEL = 'demo_model="$demo_model"'


def _target(expr: str, ref: str = "A", **extra) -> dict:
    t = {
        "refId": ref,
        "datasource": DS,
        "expr": expr,
        "instant": True,
    }
    t.update(extra)
    return t


def _pass_fail_field() -> dict:
    return {
        "defaults": {
            "mappings": [
                {
                    "type": "value",
                    "options": {
                        "0": {"text": "FAIL", "color": "red", "index": 0},
                        "1": {"text": "PASS", "color": "green", "index": 1},
                    },
                }
            ],
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "red", "value": None},
                    {"color": "green", "value": 1},
                ],
            },
            "unit": "none",
        },
        "overrides": [],
    }


def scenario_variable() -> dict:
    # Keep query ASCII-only (value list). Display labels live in options.
    # Avoid "value : text" in query — unicode/punctuation there has broken
    # Grafana custom-var parsing so $demo_model became the display string.
    opts = [
        ("hostname", "1 Hostname join (prove)"),
        ("hostname_poison", "2 Hostname mismatch (disprove)"),
        ("mac_alias", "3 MAC alias (prove)"),
        ("address", "4 Address hub (prove)"),
        ("iface", "5 Interface LLDP (prove)"),
        ("edge_attrs", "6 Attrs on edge (Q3 disprove)"),
        ("vrf", "7 MAC-VRF entity (Q3 prove)"),
    ]
    return {
        "name": "demo_model",
        "type": "custom",
        "label": "Identity tab",
        "query": ",".join(v for v, _ in opts),
        "current": {"text": "7 MAC-VRF entity (Q3 prove)", "value": "vrf", "selected": True},
        "options": [
            {"text": text, "value": value, "selected": value == "vrf"}
            for value, text in opts
        ],
        "includeAll": False,
        "multi": False,
        "hide": 0,
        "skipUrlSync": False,
    }


def scenario_intro() -> str:
    return """### Identity tabs (OTel Network Semconv open questions)

Use **Identity tab** (top variable) to switch datasets. Each `demo_model` is a parallel
entity graph from `join-app` (`entity_demo_*` metrics).

| Tab | Claim | Expected verdict |
|-----|--------|------------------|
| **Hostname join** | SNMP + LLDP both key `name:<sysName>` | observers converge |
| **Hostname mismatch** | SNMP uses `name:spine1-poller`, LLDP keeps `name:spine1` | join **fails** (no fuzzy merge) |
| **MAC alias** | LLDP primary `mac:…`, SNMP `name:…` + `same_as` alias | exact join via alias |
| **Address hub** | `network.address` `172.17.0.1/2` bridges app/flow ↔ hosts | app path joins without hostname |
| **Interface LLDP** | `connected_to` is ifName↔ifName (ports are identity, not edge attrs) | edge discipline **pass** |
| **Attrs on edge (Q3 fail)** | Device `adjacent_to` with `src_port`/`dst_port` on the edge | edge discipline **fail** |
| **MAC-VRF entity (Q3 pass)** | `network.vrf` `vrf-1` holds EVI/VNI/RT; ifaces `member_of` VRF | app in overlay; underlay iface `connected_to` |

Sanity: **entity_demo series (all models)** should be non-zero even if a tab filter is wrong.
"""


def append_identity_panels(panels: list, y: int, row_fn, md_fn) -> int:
    """Append identity scenario section. Returns next y."""
    panels.append(row_fn("Identity scenarios — prove / disprove (switch Identity tab)", 300, y))
    y += 1
    panels.append(md_fn("How to use these tabs", scenario_intro(), 301, y, h=10))
    y += 10

    # Unfiltered sanity — proves pipeline even when $demo_model is wrong
    panels.append(
        {
            "id": 320,
            "type": "stat",
            "title": "Sanity · entity_demo series (all models)",
            "description": "If this is No data, join-app identity metrics are not reaching Prometheus.",
            "gridPos": {"h": 3, "w": 8, "x": 0, "y": y},
            "datasource": DS,
            "targets": [_target("count(entity_demo_verdict)")],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 321,
            "type": "stat",
            "title": "Sanity · selected model series",
            "description": "count of verdict series for $demo_model only",
            "gridPos": {"h": 3, "w": 8, "x": 8, "y": y},
            "datasource": DS,
            "targets": [_target(f"count(entity_demo_verdict{{{MODEL}}})")],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 322,
            "type": "stat",
            "title": "Sanity · hardcoded vrf (no variable)",
            "description": "If this PASS but selected-model is empty, the Identity tab variable is broken.",
            "gridPos": {"h": 3, "w": 8, "x": 16, "y": y},
            "datasource": DS,
            "targets": [
                _target(
                    'max(entity_demo_verdict{demo_model="vrf",check="edge_discipline"})'
                )
            ],
            "fieldConfig": _pass_fail_field(),
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "background",
                "graphMode": "none",
            },
        }
    )
    y += 3

    panels.append(
        {
            "id": 302,
            "type": "stat",
            "title": "Verdict · observer_join ($demo_model)",
            "description": "1=pass, 0=fail — exact id intersection across observers",
            "gridPos": {"h": 4, "w": 4, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                _target(f'max(entity_demo_verdict{{{MODEL},check="observer_join"}})')
            ],
            "fieldConfig": _pass_fail_field(),
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "background",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 303,
            "type": "stat",
            "title": "Verdict · app_path_join",
            "gridPos": {"h": 4, "w": 4, "x": 4, "y": y},
            "datasource": DS,
            "targets": [
                _target(f'max(entity_demo_verdict{{{MODEL},check="app_path_join"}})')
            ],
            "fieldConfig": _pass_fail_field(),
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "background",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 313,
            "type": "stat",
            "title": "Verdict · edge_discipline (Q3)",
            "description": "PASS = no attrs on edges. FAIL = attrs-on-edge smell.",
            "gridPos": {"h": 4, "w": 4, "x": 8, "y": y},
            "datasource": DS,
            "targets": [
                _target(f'max(entity_demo_verdict{{{MODEL},check="edge_discipline"}})')
            ],
            "fieldConfig": _pass_fail_field(),
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "background",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 304,
            "type": "stat",
            "title": "Devices / entities",
            "gridPos": {"h": 4, "w": 6, "x": 12, "y": y},
            "datasource": DS,
            "targets": [_target(f"count(entity_demo_device_info{{{MODEL}}})")],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 305,
            "type": "stat",
            "title": "Aliases (same_as)",
            "gridPos": {"h": 4, "w": 6, "x": 18, "y": y},
            "datasource": DS,
            "targets": [
                _target(
                    f"count(entity_demo_alias_info{{{MODEL}}}) or on() vector(0)"
                )
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    y += 4

    nodes = (
        f'label_replace(label_replace(label_replace('
        f'max by (id, title, kind, observer) (entity_demo_device_info{{{MODEL}}}), '
        f'"mainStat", "$1", "observer", "(.*)"), '
        f'"arc__device", "1", "kind", ".*"), '
        f'"subTitle", "$1", "kind", "(.*)")'
    )
    addr_nodes = (
        f'label_replace(label_replace('
        f'max by (id, address, kind) (entity_demo_address_info{{{MODEL}}}), '
        f'"title", "$1", "address", "(.*)"), '
        f'"arc__address", "1", "kind", ".*")'
    )
    edges = (
        f'label_replace(label_replace(label_replace(label_replace('
        f'max by (id, src, dst, kind) (entity_demo_edge_info{{{MODEL}}}), '
        f'"source", "$1", "src", "(.*)"), '
        f'"target", "$1", "dst", "(.*)"), '
        f'"mainStat", "$1", "kind", "(.*)"), '
        f'"secondaryStat", "$1", "kind", "(.*)")'
    )
    alias_edges = (
        f'label_replace(label_replace(label_replace('
        f'max by (id, alias_id) (entity_demo_alias_info{{{MODEL}}}), '
        f'"source", "$1", "id", "(.*)"), '
        f'"target", "$1", "alias_id", "(.*)"), '
        f'"mainStat", "same_as", "id", ".*")'
    )

    panels.append(
        {
            "id": 306,
            "type": "nodeGraph",
            "title": "Entity graph · $demo_model",
            "description": "Parallel dataset for the selected identity model.",
            "gridPos": {"h": 14, "w": 14, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                _target(f"({nodes}) or ({addr_nodes})", ref="Nodes", format="table"),
                _target(f"({edges}) or ({alias_edges})", ref="Edges", format="table"),
            ],
            "options": {
                "layoutAlgorithm": "layered",
                "nodes": {"nodeRadius": 32},
                "zoomMode": "cooperative",
            },
        }
    )
    panels.append(
        {
            "id": 307,
            "type": "table",
            "title": "Device ids by observer",
            "gridPos": {"h": 7, "w": 10, "x": 14, "y": y},
            "datasource": DS,
            "targets": [_target(f"entity_demo_device_info{{{MODEL}}}", format="table")],
            "options": {"showHeader": True},
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "Value"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "tester_id"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "demo_model"}, "properties": [{"id": "custom.hidden", "value": True}]},
                ],
            },
        }
    )
    panels.append(
        {
            "id": 308,
            "type": "table",
            "title": "Aliases / addresses / VRF attrs",
            "description": "For vrf tab: network.vrf rows carry evi/vni/route_target on the entity.",
            "gridPos": {"h": 7, "w": 10, "x": 14, "y": y + 7},
            "datasource": DS,
            "targets": [
                _target(
                    f"entity_demo_alias_info{{{MODEL}}} "
                    f"or entity_demo_address_info{{{MODEL}}} "
                    f'or entity_demo_device_info{{{MODEL},kind="network.vrf"}}',
                    format="table",
                )
            ],
            "options": {"showHeader": True},
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "Value"}, "properties": [{"id": "custom.hidden", "value": True}]},
                ],
            },
        }
    )
    y += 14

    panels.append(
        {
            "id": 314,
            "type": "table",
            "title": "Edges for $demo_model (look for src_port / smell on edge_attrs)",
            "description": "Q3 disprove: adjacent_to carries src_port+dst_port+smell. Q3 prove: member_of / connected_to have no port attrs.",
            "gridPos": {"h": 7, "w": 24, "x": 0, "y": y},
            "datasource": DS,
            "targets": [_target(f"entity_demo_edge_info{{{MODEL}}}", format="table")],
            "options": {"showHeader": True},
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "Value"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "tester_id"}, "properties": [{"id": "custom.hidden", "value": True}]},
                ],
            },
        }
    )
    y += 7

    panels.append(
        {
            "id": 309,
            "type": "table",
            "title": "Live LLDP · hostname edges + chassis MAC (raw)",
            "description": "Alloy remap keeps dst_chassis_id from gnmic neighbor_id.",
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                _target(
                    'network_topology_edge_info{tester_id="$tester_id"}',
                    format="table",
                )
            ],
            "options": {"showHeader": True},
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "Value"}, "properties": [{"id": "custom.hidden", "value": True}]},
                ],
            },
        }
    )
    panels.append(
        {
            "id": 310,
            "type": "table",
            "title": "Live LLDP · port-level (src_port → dst_port)",
            "description": "network_topology_edge_port_info",
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                _target(
                    'network_topology_edge_port_info{tester_id="$tester_id"}',
                    format="table",
                )
            ],
            "options": {"showHeader": True},
            "fieldConfig": {
                "defaults": {},
                "overrides": [
                    {"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                    {"matcher": {"id": "byName", "options": "Value"}, "properties": [{"id": "custom.hidden", "value": True}]},
                ],
            },
        }
    )
    y += 8

    panels.append(
        {
            "id": 311,
            "type": "stat",
            "title": "Exact id overlap (snmp ∩ lldp) for $demo_model",
            "description": "0 on hostname_poison.",
            "gridPos": {"h": 5, "w": 12, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                _target(
                    f"count("
                    f"count by (id) (entity_demo_device_info{{{MODEL},observer=\"snmp\"}}) "
                    f"and "
                    f"count by (id) (entity_demo_device_info{{{MODEL},observer=\"lldp\"}})"
                    f") or on() vector(0)"
                )
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 312,
            "type": "stat",
            "title": "IDs reachable via same_as alias",
            "gridPos": {"h": 5, "w": 12, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                _target(
                    f"count(entity_demo_alias_info{{{MODEL}}}) or on() vector(0)"
                )
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    y += 5
    return y
