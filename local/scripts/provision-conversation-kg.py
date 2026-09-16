#!/usr/bin/env python3
"""Provision conversation recording rules + Knowledge Graph entities.

Projects ktranslate (and named-client) flows into a 4-tuple conversation
metric that drops ephemeral source ports and collector noise, then defines
Host / NetworkDevice entities so lab clients relate to SRL gear.

Usage:
  python3 local/scripts/provision-conversation-kg.py --dry-run
  python3 local/scripts/provision-conversation-kg.py
  python3 local/scripts/provision-conversation-kg.py --verify --wait 90
  python3 local/scripts/provision-conversation-kg.py --kg-only
  python3 local/scripts/provision-conversation-kg.py --delete
"""
from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
YAML_OUT = ROOT / "fixtures" / "conversation-kg" / "recording-rules.yaml"
MODEL_OUT = ROOT / "fixtures" / "conversation-kg" / "model-rules.yaml"
FOLDER_UID = "network-lab"
RULE_GROUP = "Network Lab / conversation kg"
INTERVAL_SEC = 60
PROM_DS = "grafanacloud-prom"
MODEL_NAME = "network-lab-conversation"
ASSERTS_ENV = "network-lab"
ASSERTS_SITE = "colocated"

# Collector / SNMP control-plane ports — not client conversations.
COLLECTOR_PORTS = (
    "161|162|1620|11620|1514|1515|9995|19995|2055|6343|6344"
)
CLIENT = 'src_host=~"client.*", dst_host=~"client.*"'
CLIENT_SRC = 'src_host=~"client.*"'
CLIENT_DST = 'dst_host=~"client.*"'
NOISE = f'network_peer_port!~"^({COLLECTOR_PORTS})$"'

# EVPN access attach: clients sit on leaf ethernet-1/1 (join-app overlay).
ATTACH = (
    ("client1", "leaf1"),
    ("client2", "leaf2"),
    ("client-br1", "leaf-br1"),
    ("client-br2", "leaf-br2"),
)
# Role-bearing access ports as Interface entities (not spine ethernet-1/1 — that is WAN).
ACCESS_IFACES = (
    ("leaf1", "ethernet-1/1"),
    ("leaf2", "ethernet-1/1"),
    ("leaf-br1", "ethernet-1/1"),
    ("leaf-br2", "ethernet-1/1"),
)
# Clos underlay. Live LLDP is incomplete (leaf1 often missing); keep a catalog.
FABRIC = (
    ("leaf1", "spine1"),
    ("leaf2", "spine1"),
    ("leaf-br1", "spine1"),
    ("leaf-br2", "spine1"),
)
# Interface-to-interface (NetBox cables + WAN circuits). Both directions so
# expanding either port draws ROUTES. Access ports attach Hosts, not Interfaces.
IFACE_LINKS = (
    ("spine1", "ethernet-1/1", "leaf1", "ethernet-1/49"),
    ("spine1", "ethernet-1/2", "leaf2", "ethernet-1/49"),
    ("spine1", "ethernet-1/3", "leaf-br1", "ethernet-1/49"),
    ("spine1", "ethernet-1/4", "leaf-br2", "ethernet-1/49"),
)
# Physical ethernet only — skip mgmt/system and .0 subinterfaces.
PHYS_ETH = 'if_interface_name=~"^ethernet-[0-9]+/[0-9]+$"'


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


def _static_or(pairs: list[tuple[str, str]], left: str, right: str) -> str:
    parts = []
    for a, b in pairs:
        parts.append(
            f'  label_replace(label_replace(vector(1), "{left}", "{a}", "", ""), '
            f'"{right}", "{b}", "", "")'
        )
    return "\nor\n".join(parts)


def _conversation_bytes() -> str:
    # ktranslate flow rollups are gauges (last interval bytes) — not counters.
    return f"""
sum by (src_host, dst_host, network_peer_port, network_transport) (
  max_over_time(
    network_io_by_flow_bytes{{{CLIENT}, {NOISE}}}[5m]
  )
)
""".strip()


def _host_pair() -> str:
    return f"""
sum by (src_host, dst_host) (
  max_over_time(
    network_io_by_flow_bytes{{{CLIENT}, {NOISE}}}[5m]
  )
)
""".strip()


def _host_info() -> str:
    return f"""
count by (host) (
  label_replace(
    network_io_by_flow_bytes{{{CLIENT_SRC}}},
    "host", "$1", "src_host", "(.+)"
  )
  or
  label_replace(
    network_io_by_flow_bytes{{{CLIENT_DST}}},
    "host", "$1", "dst_host", "(.+)"
  )
)
""".strip()


def _device_info() -> str:
    return """
count by (device_name) (kentik_snmp_CPU)
or
count by (device_name) (snmp_CPU)
""".strip()


def _attached() -> str:
    return _static_or(list(ATTACH), "host", "device_name")


def _iface_join(inner: str) -> str:
    return f"""
label_join(
  {inner},
  "interface", ":", "device_name", "if_interface_name"
)
""".strip()


def _iface_access() -> str:
    parts = []
    for device, iface in ACCESS_IFACES:
        parts.append(
            "  label_replace(label_replace(label_replace(vector(1), "
            f'"device_name", "{device}", "", ""), '
            f'"if_interface_name", "{iface}", "", ""), '
            '"iface_role", "access", "", "")'
        )
    return "\nor\n".join(parts)


def _iface_wan() -> str:
    return f"""
label_replace(
  count by (device_name, if_interface_name) (
    kentik_snmp_if_OperStatus{{if_Alias=~".*WAN.*", {PHYS_ETH}}}
    and on (device_name) kentik_snmp_CPU
  ),
  "iface_role", "wan", "", ""
)
""".strip()


def _iface_fault() -> str:
    # Lazy: unused ports stay off the graph until they are admin-up/oper-down.
    return f"""
label_replace(
  count by (device_name, if_interface_name) (
    kentik_snmp_if_OperStatus{{
      if_AdminStatus="up",
      if_OperStatus="down",
      {PHYS_ETH}
    }}
    and on (device_name) kentik_snmp_CPU
  ),
  "iface_role", "fault", "", ""
)
""".strip()


def _iface_catalog() -> str:
    # Same ports as IFACE_LINKS, with peer_interface so KG can PROPERTY_MATCH
    # Interface ROUTES Interface (METRICS alone needs lookup aliases).
    parts = []
    for a_dev, a_if, b_dev, b_if in IFACE_LINKS:
        for device, iface, peer_dev, peer_if in (
            (a_dev, a_if, b_dev, b_if),
            (b_dev, b_if, a_dev, a_if),
        ):
            peer = f"{peer_dev}:{peer_if}"
            parts.append(
                "  label_replace(label_replace(label_replace(label_replace(vector(1), "
                f'"device_name", "{device}", "", ""), '
                f'"if_interface_name", "{iface}", "", ""), '
                '"iface_role", "fabric", "", ""), '
                f'"peer_interface", "{peer}", "", "")'
            )
    return "\nor\n".join(parts)


def _iface_info() -> str:
    # ~12 Clos role-bearing ports, not the full IF-MIB table (~44).
    return _iface_join(
        f"{_iface_access()}\nor\n{_iface_wan()}\nor\n{_iface_fault()}\nor\n{_iface_catalog()}"
    )


def _iface_connected_catalog() -> str:
    parts = []
    for a_dev, a_if, b_dev, b_if in IFACE_LINKS:
        a = f"{a_dev}:{a_if}"
        b = f"{b_dev}:{b_if}"
        for src, dst in ((a, b), (b, a)):
            parts.append(
                "  label_replace(label_replace(vector(1), "
                f'"src_interface", "{src}", "", ""), '
                f'"dst_interface", "{dst}", "", "")'
            )
    return "\nor\n".join(parts)


def _iface_connected_live() -> str:
    # Observed L2 (gnmic / SNMP LLDP) when both ports are named. gnmic uses
    # Eth-1/49; KG Interface names are ethernet-1/49. BGP sessions have no
    # dst_port and stay device-level only.
    return """
label_replace(
  label_replace(
    label_join(
      label_join(
        count by (src_device, src_port, dst_device, dst_port) (
          network_topology_edge_info{
            src_port!="",
            src_port!="INTERFACE_NAME",
            dst_port!="",
            dst_port!="INTERFACE_NAME"
          }
        ),
        "src_interface", ":", "src_device", "src_port"
      ),
      "dst_interface", ":", "dst_device", "dst_port"
    ),
    "src_interface", "${1}:ethernet-${2}", "src_interface", "([^:]+):Eth-(.+)"
  ),
  "dst_interface", "${1}:ethernet-${2}", "dst_interface", "([^:]+):Eth-(.+)"
)
""".strip()


def _iface_connected() -> str:
    return f"{_iface_connected_catalog()}\nor\n{_iface_connected_live()}"


def _connected() -> str:
    catalog = _static_or(list(FABRIC), "src_device", "dst_device")
    live = """
(
  count by (src_device, dst_device) (network_topology_edge_info)
  unless on (src_device, dst_device)
    label_replace(
      count by (src_device) (network_topology_edge_info),
      "dst_device", "$1", "src_device", "(.*)"
    )
)
""".strip()
    return f"{catalog}\nor\n{live}"


def _routes() -> str:
    # Built-in service-graph feed (any positive value). Custom Host/NetworkDevice
    # relations use the conversation/attach/fabric metrics directly.
    host_pair = f"""
label_replace(
  label_replace(
    {_host_pair()},
    "job", "$1", "src_host", "(.*)"
  ),
  "dst_job", "$1", "dst_host", "(.*)"
)
""".strip()
    attach = f"""
label_replace(
  label_replace(
    {_attached()},
    "job", "$1", "host", "(.*)"
  ),
  "dst_job", "$1", "device_name", "(.*)"
)
""".strip()
    fabric = f"""
label_replace(
  label_replace(
    {_connected()},
    "job", "$1", "src_device", "(.*)"
  ),
  "dst_job", "$1", "dst_device", "(.*)"
)
""".strip()
    return f"{host_pair}\nor\n{attach}\nor\n{fabric}"


def rule_specs() -> list[dict[str, str]]:
    return [
        {
            "uid": "nlab-conv-bytes5m",
            "title": "conversation 4-tuple bytes (no src port)",
            "record": "conversation:network_io:bytes5m",
            "expr": _conversation_bytes(),
        },
        {
            "uid": "nlab-conv-host-pair",
            "title": "conversation host pair bytes",
            "record": "conversation:host_pair:bytes5m",
            "expr": _host_pair(),
        },
        {
            "uid": "nlab-conv-host-info",
            "title": "lab client hosts",
            "record": "network_lab:host_info",
            "expr": _host_info(),
        },
        {
            "uid": "nlab-conv-device-info",
            "title": "SRL network devices",
            "record": "network_lab:device_info",
            "expr": _device_info(),
        },
        {
            "uid": "nlab-conv-attached",
            "title": "client attached to leaf",
            "record": "network_lab:host_attached:info",
            "expr": _attached(),
        },
        {
            "uid": "nlab-conv-connected",
            "title": "SRL fabric edges",
            "record": "network_lab:device_connected:info",
            "expr": _connected(),
        },
        {
            "uid": "nlab-conv-iface-info",
            "title": "role-bearing / faulted interfaces",
            "record": "network_lab:interface_info",
            "expr": _iface_info(),
        },
        {
            "uid": "nlab-conv-iface-connected",
            "title": "interface to interface fabric/WAN",
            "record": "network_lab:interface_connected:info",
            "expr": _iface_connected(),
        },
        {
            "uid": "nlab-conv-routes",
            "title": "KG service-graph routes",
            "record": "asserts:relation:routes",
            "expr": _routes(),
        },
    ]


def _scope_match(name_label: str) -> dict[str, str]:
    # Scoped entities are (name, env, site). Matchers that omit env/site never join.
    return {
        "name": name_label,
        "env": "asserts_env",
        "site": "asserts_site",
    }


def model_rules() -> dict[str, Any]:
    # HOSTS / ROUTES are the edge types the entity graph actually draws.
    # Custom FLOWS_TO / ATTACHED_TO / CONNECTED_TO harvest entities but often
    # never show as lines. Direction: device HOSTS client (leaf hosts client).
    return {
        "name": MODEL_NAME,
        "entities": [
            {
                "type": "Host",
                "name": "host",
                "scope": {"env": "asserts_env", "site": "asserts_site"},
                "lookup": {"host": "host | src_host | dst_host"},
                "definedBy": [
                    {
                        "query": (
                            "group by (host, asserts_env, asserts_site) "
                            "(network_lab:host_info{asserts_env!=\"\"})"
                        ),
                        "literals": {"role": "lab-client", "layer": "compute"},
                    }
                ],
                "enrichedBy": [
                    {
                        "query": (
                            "group by (host, device_name, asserts_env, asserts_site) "
                            "(network_lab:host_attached:info{asserts_env!=\"\"})"
                        ),
                        "labelValues": {"device_name": "device_name"},
                    }
                ],
            },
            {
                "type": "NetworkDevice",
                "name": "device_name",
                "scope": {"env": "asserts_env", "site": "asserts_site"},
                "lookup": {
                    "device_name": "device_name | src_device | dst_device",
                },
                "definedBy": [
                    {
                        "query": (
                            "group by (device_name, asserts_env, asserts_site) "
                            "(network_lab:device_info{asserts_env!=\"\"})"
                        ),
                        "literals": {"role": "srl", "layer": "network"},
                    }
                ],
            },
            {
                "type": "Interface",
                "name": "interface",
                "scope": {"env": "asserts_env", "site": "asserts_site"},
                "lookup": {
                    "interface": "interface | src_interface | dst_interface",
                },
                "definedBy": [
                    {
                        "query": (
                            "group by (interface, device_name, if_interface_name, "
                            "asserts_env, asserts_site) "
                            "(network_lab:interface_info{asserts_env!=\"\"})"
                        ),
                        "literals": {"layer": "l1-l3"},
                        "labelValues": {
                            "device_name": "device_name",
                            "if_interface_name": "if_interface_name",
                        },
                    }
                ],
                "enrichedBy": [
                    {
                        "query": (
                            "group by (interface, iface_role, asserts_env, asserts_site) "
                            "(network_lab:interface_info{asserts_env!=\"\"})"
                        ),
                        "labelValues": {"iface_role": "iface_role"},
                    },
                    {
                        "query": (
                            "group by (interface, peer_interface, asserts_env, asserts_site) "
                            "(network_lab:interface_info{peer_interface!=\"\"})"
                        ),
                        "labelValues": {"peer_interface": "peer_interface"},
                    },
                ],
            },
        ],
        "relations": [
            {
                "type": "ROUTES",
                "startEntityType": "Host",
                "endEntityType": "Host",
                "definedBy": {
                    "source": "METRICS",
                    "pattern": (
                        "group by (src_host, dst_host, asserts_env, asserts_site) ("
                        "  conversation:host_pair:bytes5m{asserts_env!=\"\"}"
                        ")"
                    ),
                    "startEntityMatchers": _scope_match("src_host"),
                    "endEntityMatchers": _scope_match("dst_host"),
                },
            },
            {
                "type": "HOSTS",
                "startEntityType": "NetworkDevice",
                "endEntityType": "Host",
                "definedBy": {
                    "source": "PROPERTY_MATCH",
                    "startEntityProperties": ["name", "env", "site"],
                    "endEntityProperties": ["device_name", "env", "site"],
                },
            },
            {
                "type": "HOSTS",
                "startEntityType": "NetworkDevice",
                "endEntityType": "Host",
                "definedBy": {
                    "source": "METRICS",
                    "pattern": (
                        "group by (host, device_name, asserts_env, asserts_site) ("
                        "  network_lab:host_attached:info{asserts_env!=\"\"}"
                        ")"
                    ),
                    "startEntityMatchers": _scope_match("device_name"),
                    "endEntityMatchers": _scope_match("host"),
                },
            },
            {
                "type": "ROUTES",
                "startEntityType": "NetworkDevice",
                "endEntityType": "NetworkDevice",
                "definedBy": {
                    "source": "METRICS",
                    "pattern": (
                        "group by (src_device, dst_device, asserts_env, asserts_site) ("
                        "  network_lab:device_connected:info{asserts_env!=\"\"}"
                        ")"
                    ),
                    "startEntityMatchers": _scope_match("src_device"),
                    "endEntityMatchers": _scope_match("dst_device"),
                },
            },
            {
                "type": "HOSTS",
                "startEntityType": "NetworkDevice",
                "endEntityType": "Interface",
                "definedBy": {
                    "source": "PROPERTY_MATCH",
                    "startEntityProperties": ["name", "env", "site"],
                    "endEntityProperties": ["device_name", "env", "site"],
                },
            },
            {
                "type": "HOSTS",
                "startEntityType": "NetworkDevice",
                "endEntityType": "Interface",
                "definedBy": {
                    "source": "METRICS",
                    "pattern": (
                        "group by (interface, device_name, asserts_env, asserts_site) ("
                        "  network_lab:interface_info{asserts_env!=\"\"}"
                        ")"
                    ),
                    "startEntityMatchers": _scope_match("device_name"),
                    "endEntityMatchers": _scope_match("interface"),
                },
            },
            {
                "type": "ROUTES",
                "startEntityType": "Interface",
                "endEntityType": "Interface",
                "definedBy": {
                    "source": "PROPERTY_MATCH",
                    "startEntityProperties": ["peer_interface", "env", "site"],
                    "endEntityProperties": ["name", "env", "site"],
                },
            },
            {
                "type": "ROUTES",
                "startEntityType": "Interface",
                "endEntityType": "Interface",
                "definedBy": {
                    "source": "METRICS",
                    "pattern": (
                        "group by (src_interface, dst_interface, asserts_env, asserts_site) ("
                        "  network_lab:interface_connected:info{asserts_env!=\"\"}"
                        ")"
                    ),
                    "startEntityMatchers": _scope_match("src_interface"),
                    "endEntityMatchers": _scope_match("dst_interface"),
                },
            },
        ],
    }


def grafana_rule(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "uid": spec["uid"],
        "title": spec["title"],
        "for": "0s",
        "orgId": 1,
        "labels": {
            "source": "network-lab",
            "kind": "conversation",
            "asserts_env": ASSERTS_ENV,
            "asserts_site": ASSERTS_SITE,
        },
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 1800, "to": 0},
                "datasourceUid": PROM_DS,
                "model": {
                    "datasource": {"type": "prometheus", "uid": PROM_DS},
                    "expr": spec["expr"],
                    "instant": True,
                    "intervalMs": 1000,
                    "legendFormat": "__auto",
                    "maxDataPoints": 43200,
                    "refId": "A",
                },
            }
        ],
        "record": {
            "metric": spec["record"],
            "from": "A",
            "target_datasource_uid": PROM_DS,
        },
        "isPaused": False,
    }


def export_yaml(specs: list[dict[str, str]]) -> None:
    lines = [
        "# Conversation / KG recording rules for the colocated lab.",
        "# Source of truth is provision-conversation-kg.py (this file is exported).",
        "#",
        "# 4-tuple is src_host, dst_host, network_peer_port, network_transport.",
        "# Ephemeral source ports are never recorded. Collector ports are dropped.",
        "# Flow device_name is the exporter (client), not the SRL hop — attach is",
        "# a lab catalog (client→leaf), fabric is catalog ∪ live LLDP.",
        "#",
        f"# Load: python3 local/scripts/provision-conversation-kg.py",
        "",
        "groups:",
        f"  - name: conversation.kg",
        "    interval: 1m",
        "    rules:",
    ]
    for spec in specs:
        expr = spec["expr"].rstrip() + "\n"
        indented = "".join(
            ("          " + ln if ln.strip() else "\n") for ln in expr.splitlines(True)
        )
        lines.append(f"      - record: {spec['record']}")
        lines.append(f"        # {spec['title']}")
        lines.append("        labels:")
        lines.append(f"          asserts_env: {ASSERTS_ENV}")
        lines.append(f"          asserts_site: {ASSERTS_SITE}")
        lines.append("        expr: |")
        lines.append(indented.rstrip("\n"))
        lines.append("")
    YAML_OUT.parent.mkdir(parents=True, exist_ok=True)
    YAML_OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def export_model() -> None:
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    text = f"""# Knowledge Graph custom model for the colocated Clos lab.
# Source of truth is provision-conversation-kg.py (this file is exported).
# Paste into Grafana: Observability → Rules → Entity & Relation → New rule file.
#
# Use HOSTS / ROUTES (types the entity graph draws). Custom FLOWS_TO lines
# often never appear. Device HOSTS client; Host ROUTES Host; leaf ROUTES spine.
# Device HOSTS Interface; Interface ROUTES Interface (catalog + live LLDP).
# Interface lookup aliases src_interface|dst_interface (same pattern as Host).
# Matchers include env/site because those entities are scoped.

name: {MODEL_NAME}
entities:
  - type: Host
    name: host
    scope:
      env: asserts_env
      site: asserts_site
    lookup:
      host: host | src_host | dst_host
    definedBy:
      - query: group by (host, asserts_env, asserts_site) (network_lab:host_info{{asserts_env!=""}})
        literals:
          role: lab-client
          layer: compute
    enrichedBy:
      - query: group by (host, device_name, asserts_env, asserts_site) (network_lab:host_attached:info{{asserts_env!=""}})
        labelValues:
          device_name: device_name
  - type: NetworkDevice
    name: device_name
    scope:
      env: asserts_env
      site: asserts_site
    lookup:
      device_name: device_name | src_device | dst_device
    definedBy:
      - query: group by (device_name, asserts_env, asserts_site) (network_lab:device_info{{asserts_env!=""}})
        literals:
          role: srl
          layer: network
  - type: Interface
    name: interface
    scope:
      env: asserts_env
      site: asserts_site
    lookup:
      interface: interface | src_interface | dst_interface
    definedBy:
      - query: group by (interface, device_name, if_interface_name, asserts_env, asserts_site) (network_lab:interface_info{{asserts_env!=""}})
        literals:
          layer: l1-l3
        labelValues:
          device_name: device_name
          if_interface_name: if_interface_name
    enrichedBy:
      - query: group by (interface, iface_role, asserts_env, asserts_site) (network_lab:interface_info{{asserts_env!=""}})
        labelValues:
          iface_role: iface_role
      - query: group by (interface, peer_interface, asserts_env, asserts_site) (network_lab:interface_info{{peer_interface!=""}})
        labelValues:
          peer_interface: peer_interface
relations:
  - type: ROUTES
    startEntityType: Host
    endEntityType: Host
    definedBy:
      source: METRICS
      pattern: |-
        group by (src_host, dst_host, asserts_env, asserts_site) (
          conversation:host_pair:bytes5m{{asserts_env!=""}}
        )
      startEntityMatchers:
        name: src_host
        env: asserts_env
        site: asserts_site
      endEntityMatchers:
        name: dst_host
        env: asserts_env
        site: asserts_site
  - type: HOSTS
    startEntityType: NetworkDevice
    endEntityType: Host
    definedBy:
      source: PROPERTY_MATCH
      startEntityProperties: [name, env, site]
      endEntityProperties: [device_name, env, site]
  - type: HOSTS
    startEntityType: NetworkDevice
    endEntityType: Host
    definedBy:
      source: METRICS
      pattern: |-
        group by (host, device_name, asserts_env, asserts_site) (
          network_lab:host_attached:info{{asserts_env!=""}}
        )
      startEntityMatchers:
        name: device_name
        env: asserts_env
        site: asserts_site
      endEntityMatchers:
        name: host
        env: asserts_env
        site: asserts_site
  - type: ROUTES
    startEntityType: NetworkDevice
    endEntityType: NetworkDevice
    definedBy:
      source: METRICS
      pattern: |-
        group by (src_device, dst_device, asserts_env, asserts_site) (
          network_lab:device_connected:info{{asserts_env!=""}}
        )
      startEntityMatchers:
        name: src_device
        env: asserts_env
        site: asserts_site
      endEntityMatchers:
        name: dst_device
        env: asserts_env
        site: asserts_site
  - type: HOSTS
    startEntityType: NetworkDevice
    endEntityType: Interface
    definedBy:
      source: PROPERTY_MATCH
      startEntityProperties: [name, env, site]
      endEntityProperties: [device_name, env, site]
  - type: HOSTS
    startEntityType: NetworkDevice
    endEntityType: Interface
    definedBy:
      source: METRICS
      pattern: |-
        group by (interface, device_name, asserts_env, asserts_site) (
          network_lab:interface_info{{asserts_env!=""}}
        )
      startEntityMatchers:
        name: device_name
        env: asserts_env
        site: asserts_site
      endEntityMatchers:
        name: interface
        env: asserts_env
        site: asserts_site
  - type: ROUTES
    startEntityType: Interface
    endEntityType: Interface
    definedBy:
      source: PROPERTY_MATCH
      startEntityProperties: [peer_interface, env, site]
      endEntityProperties: [name, env, site]
  - type: ROUTES
    startEntityType: Interface
    endEntityType: Interface
    definedBy:
      source: METRICS
      pattern: |-
        group by (src_interface, dst_interface, asserts_env, asserts_site) (
          network_lab:interface_connected:info{{asserts_env!=""}}
        )
      startEntityMatchers:
        name: src_interface
        env: asserts_env
        site: asserts_site
      endEntityMatchers:
        name: dst_interface
        env: asserts_env
        site: asserts_site
"""
    MODEL_OUT.write_text(text, encoding="utf-8")


def http_json(
    env: dict[str, str],
    method: str,
    path: str,
    body: Any | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    headers = {
        "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Disable-Provenance": "true",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:4000]}
        return exc.code, payload


def group_path(name: str, folder: str = FOLDER_UID) -> str:
    return (
        f"/api/v1/provisioning/folder/{folder}/rule-groups/"
        f"{urllib.parse.quote(name, safe='')}"
    )


def stack_id(env: dict[str, str]) -> str:
    status, data = http_json(env, "GET", "/api/plugins/grafana-asserts-app/settings")
    if 200 <= int(status) < 300 and isinstance(data, dict):
        sid = (data.get("jsonData") or {}).get("stackId")
        if sid:
            return str(sid)
    return str(env.get("GC_OTLP_ACCOUNT") or "1061129")


def asserts_headers(env: dict[str, str]) -> dict[str, str]:
    return {"X-Scope-OrgID": stack_id(env)}


def asserts_path(suffix: str) -> str:
    return "/api/plugins/grafana-asserts-app/resources/asserts/api-server" + suffix


def kg_status(env: dict[str, str]) -> dict[str, Any]:
    status, data = http_json(
        env, "GET", asserts_path("/v1/stack/status"), extra_headers=asserts_headers(env)
    )
    if not (200 <= int(status) < 300) or not isinstance(data, dict):
        return {"http": status, "body": data}
    return data


def enable_kg(env: dict[str, str]) -> None:
    hdrs = {**asserts_headers(env), "Content-Type": "application/json"}
    st = kg_status(env)
    if st.get("enabled") is True:
        print(f"Knowledge Graph already enabled (status={st.get('status')})")
        return
    print(f"Knowledge Graph status={st.get('status')} enabled={st.get('enabled')}")
    auto_status, auto_body = http_json(
        env,
        "POST",
        asserts_path("/v2/stack/datasets/auto-setup"),
        body={},
        extra_headers=hdrs,
    )
    print(f"dataset auto-setup -> {auto_status}: {auto_body}")
    en_status, en_body = http_json(
        env,
        "POST",
        asserts_path("/v2/stack/enable"),
        body={},
        extra_headers=hdrs,
    )
    print(f"stack enable -> {en_status}: {en_body}")


def put_model_rules(env: dict[str, str], *, wait_sec: int = 0) -> bool:
    deadline = time.time() + max(wait_sec, 0)
    body = model_rules()
    last: tuple[int, Any] = (0, None)
    while True:
        last = http_json(
            env,
            "PUT",
            asserts_path("/v1/config/model-rules"),
            body=body,
            extra_headers=asserts_headers(env),
        )
        status, out = last
        if 200 <= int(status) < 300:
            print(f"PUT model-rules {MODEL_NAME} -> {status}")
            return True
        msg = ""
        if isinstance(out, dict):
            msg = str(out.get("message") or out)
        else:
            msg = str(out)
        pending = "not enabled" in msg.lower() or int(status) == 403
        if pending and time.time() < deadline:
            print(f"KG not ready ({status}: {msg}); retrying…")
            time.sleep(15)
            continue
        print(f"PUT model-rules failed {status}: {out}")
        print(
            f"Paste {MODEL_OUT} into Observability → Rules → Entity & Relation "
            "once Knowledge Graph finishes enabling."
        )
        return False


def delete_model_rules(env: dict[str, str]) -> None:
    status, out = http_json(
        env,
        "DELETE",
        asserts_path(f"/v1/config/model-rules/{urllib.parse.quote(MODEL_NAME, safe='')}"),
        extra_headers=asserts_headers(env),
    )
    if status not in (200, 202, 204, 404):
        raise RuntimeError(f"DELETE model-rules -> {status}: {out}")
    print(f"Deleted KG model {MODEL_NAME} (status {status})")


def promql(env: dict[str, str], expr: str) -> list:
    base = env["GRAFANA_URL"].rstrip("/")
    q = urllib.parse.urlencode({"query": expr})
    url = f"{base}/api/datasources/proxy/uid/{PROM_DS}/api/v1/query?{q}"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        body = json.loads(resp.read().decode())
    if body.get("status") != "success":
        return []
    return body.get("data", {}).get("result") or []


def provision_rules(env: dict[str, str], *, dry_run: bool, folder: str) -> None:
    specs = rule_specs()
    export_yaml(specs)
    export_model()
    if dry_run:
        print(
            f"dry-run: would PUT {group_path(RULE_GROUP, folder)} "
            f"interval={INTERVAL_SEC}s rules={len(specs)}"
        )
        for spec in specs:
            print(f"  - {spec['record']}")
        print(f"Wrote {YAML_OUT}")
        print(f"Wrote {MODEL_OUT}")
        return

    body = {
        "title": RULE_GROUP,
        "interval": INTERVAL_SEC,
        "rules": [grafana_rule(s) for s in specs],
    }
    status, out = http_json(env, "PUT", group_path(RULE_GROUP, folder), body)
    if status == 404:
        status, out = http_json(
            env, "POST", f"/api/v1/provisioning/folder/{folder}/rule-groups", body
        )
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT/POST {RULE_GROUP} -> {status}: {out}")
    print(f"Provisioned {len(specs)} rules in {folder} / {RULE_GROUP} ({INTERVAL_SEC}s)")
    for spec in specs:
        print(f"  - {spec['record']}")


def delete_rules(env: dict[str, str], *, folder: str) -> None:
    status, out = http_json(env, "DELETE", group_path(RULE_GROUP, folder))
    if status not in (200, 202, 204, 404):
        raise RuntimeError(f"DELETE {RULE_GROUP} -> {status}: {out}")
    print(f"Deleted rule group {RULE_GROUP} (status {status})")


def verify(env: dict[str, str], *, wait_sec: int = 0) -> None:
    if wait_sec:
        print(f"waiting {wait_sec}s for first evaluation…")
        time.sleep(wait_sec)
    for spec in rule_specs():
        name = spec["record"]
        rows = promql(env, f"count({name})")
        n = rows[0]["value"][1] if rows else "0"
        print(f"  {name}  series={n}")
    print("hosts:")
    for row in promql(env, "count by (host) (network_lab:host_info)"):
        print(f"  {row.get('metric', {})} = {row.get('value', [None, '?'])[1]}")
    print("devices:")
    for row in promql(env, "count by (device_name) (network_lab:device_info)"):
        print(f"  {row.get('metric', {})} = {row.get('value', [None, '?'])[1]}")
    print("attached:")
    for row in promql(
        env, "count by (host, device_name) (network_lab:host_attached:info)"
    ):
        print(f"  {row.get('metric', {})}")
    print("interfaces:")
    for row in promql(
        env,
        "count by (interface, iface_role) (network_lab:interface_info)",
    ):
        print(f"  {row.get('metric', {})}")
    print("iface links:")
    for row in promql(
        env,
        "count by (src_interface, dst_interface) (network_lab:interface_connected:info)",
    ):
        print(f"  {row.get('metric', {})}")
    print("conversations:")
    for row in promql(
        env, "count by (src_host, dst_host) (conversation:host_pair:bytes5m)"
    ):
        print(f"  {row.get('metric', {})}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--kg-only", action="store_true", help="Skip recording rules")
    ap.add_argument("--skip-kg", action="store_true", help="Skip Knowledge Graph PUT")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--wait", type=int, default=0)
    ap.add_argument("--wait-kg", type=int, default=120)
    ap.add_argument("--folder", default=FOLDER_UID)
    args = ap.parse_args()

    specs = rule_specs()
    if args.export_only:
        export_yaml(specs)
        export_model()
        print(f"Wrote {YAML_OUT}")
        print(f"Wrote {MODEL_OUT}")
        return 0

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    if args.delete:
        if args.dry_run:
            print(f"dry-run: would DELETE {RULE_GROUP} and model {MODEL_NAME}")
            return 0
        delete_rules(env, folder=args.folder)
        delete_model_rules(env)
        return 0

    if not args.kg_only:
        provision_rules(env, dry_run=args.dry_run, folder=args.folder)
    else:
        export_yaml(specs)
        export_model()

    if args.dry_run:
        print("dry-run: would enable KG (if needed) and PUT model-rules")
        return 0

    if not args.skip_kg:
        enable_kg(env)
        put_model_rules(env, wait_sec=args.wait_kg)

    if args.verify:
        verify(env, wait_sec=args.wait)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
