#!/usr/bin/env python3
"""Populate NetBox with lab Clos topology (idempotent).

Laptop profile: HQ Clos only (spine1/leaf1/leaf2 + client1/2).
Colocated profile: 3 sites (hq / branch1 / branch2), clients, IPAM, fabric
cables, access attach, and WAN circuits. Overlays Orb-discovered devices
(roles/sites/cables) without deleting extra SNMP interfaces.

Usage:
  python3 local/scripts/netbox-populate.py
  python3 local/scripts/netbox-populate.py --profile colocated
  python3 local/scripts/netbox-populate.py --profile colocated --tidy-only
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from lab_env import load_dotenv, netbox_auth_header, netbox_url_for_host

PUBLIC_NETBOX = (
    "http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000"
)

REGION = {"name": "Lab Region", "slug": "lab-region", "description": "Synthetic region for demo inventory"}
TENANT = {"name": "Network O11y Demo", "slug": "network-o11y-demo"}
MANUFACTURER = {"name": "Nokia", "slug": "nokia"}
PLATFORM = {"name": "SR Linux", "slug": "sr-linux"}
DEVICE_TYPES = [
    {"model": "7220 IXR-D2L", "slug": "7220-ixr-d2l", "u_height": 1},
    {"model": "network-multitool", "slug": "network-multitool", "u_height": 1},
]


def live_comment(role: str, name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"network-o11y-demo | role={role} | "
        f"last_inventory_sync={ts} | source=netbox-populate.py"
    )


def laptop_topology() -> dict[str, Any]:
    return {
        "sites": [
            {
                "name": "Network Lab",
                "slug": "network-lab",
                "description": "WSL ContainerLab Clos — network-o11y-demo local path",
                "physical_address": "WSL2 ContainerLab (synthetic)",
            }
        ],
        "racks": [
            {
                "name": "Lab Rack 1",
                "slug": "lab-rack-1",
                "site": "network-lab",
                "u_height": 8,
                "comments": "Clos demo rack — spine + leaves + EVPN clients",
            }
        ],
        "roles": [
            {"name": "Spine", "slug": "spine", "color": "2196f3", "vm_role": False},
            {"name": "Leaf", "slug": "leaf", "color": "4caf50", "vm_role": False},
            {"name": "Client", "slug": "client", "color": "9e9e9e", "vm_role": False},
        ],
        "devices": [
            {"name": "spine1", "role": "spine", "type": "7220-ixr-d2l", "site": "network-lab", "rack": "lab-rack-1", "position": 1, "platform": True},
            {"name": "leaf1", "role": "leaf", "type": "7220-ixr-d2l", "site": "network-lab", "rack": "lab-rack-1", "position": 2, "platform": True},
            {"name": "leaf2", "role": "leaf", "type": "7220-ixr-d2l", "site": "network-lab", "rack": "lab-rack-1", "position": 3, "platform": True},
            {"name": "client1", "role": "client", "type": "network-multitool", "site": "network-lab", "rack": "lab-rack-1", "position": 4, "platform": False},
            {"name": "client2", "role": "client", "type": "network-multitool", "site": "network-lab", "rack": "lab-rack-1", "position": 5, "platform": False},
        ],
        "device_live": {
            "spine1": {"serial": "NSRLAB-SPN-001", "asset_tag": "LAB-RACK1-U1"},
            "leaf1": {"serial": "NSRLAB-LF-001", "asset_tag": "LAB-RACK1-U2"},
            "leaf2": {"serial": "NSRLAB-LF-002", "asset_tag": "LAB-RACK1-U3"},
            "client1": {"serial": "LAB-CLT-001", "asset_tag": "LAB-RACK1-U4"},
            "client2": {"serial": "LAB-CLT-002", "asset_tag": "LAB-RACK1-U5"},
        },
        "interfaces": [
            ("spine1", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("spine1", "ethernet-1/1", "10gbase-x-sfpp", "Uplink to leaf1 — oper up"),
            ("spine1", "ethernet-1/2", "10gbase-x-sfpp", "Uplink to leaf2 — oper up"),
            ("leaf1", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("leaf1", "ethernet-1/49", "10gbase-x-sfpp", "Downlink to spine1 — oper up"),
            ("leaf1", "ethernet-1/1", "10gbase-x-sfpp", "Access to client1 — oper up"),
            ("leaf2", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("leaf2", "ethernet-1/49", "10gbase-x-sfpp", "Downlink to spine1 — oper up"),
            ("leaf2", "ethernet-1/1", "10gbase-x-sfpp", "Access to client2 — oper up"),
            ("client1", "eth0", "1000base-t", "Management"),
            ("client1", "eth1", "1000base-t", "EVPN fabric — 172.17.0.1/24"),
            ("client2", "eth0", "1000base-t", "Management"),
            ("client2", "eth1", "1000base-t", "EVPN fabric — 172.17.0.2/24"),
        ],
        "prefixes": [
            {"prefix": "172.20.20.0/24", "site": "network-lab", "description": "ContainerLab mgmt (clab)"},
            {"prefix": "172.17.0.0/24", "site": "network-lab", "description": "EVPN overlay client subnet"},
            {"prefix": "192.168.0.0/16", "site": "network-lab", "description": "eBGP underlay /31 links"},
        ],
        "client_ips": {
            "client1": ("172.17.0.1/24", "eth1"),
            "client2": ("172.17.0.2/24", "eth1"),
        },
        "underlay_ips": [
            ("spine1", "ethernet-1/1", "192.168.11.1/31"),
            ("leaf1", "ethernet-1/49", "192.168.11.0/31"),
            ("spine1", "ethernet-1/2", "192.168.21.1/31"),
            ("leaf2", "ethernet-1/49", "192.168.21.0/31"),
        ],
        "cables": [
            ("spine1", "ethernet-1/1", "leaf1", "ethernet-1/49", "lab-fabric", "mmf"),
            ("spine1", "ethernet-1/2", "leaf2", "ethernet-1/49", "lab-fabric", "mmf"),
            ("leaf1", "ethernet-1/1", "client1", "eth1", "lab-access", "cat6"),
            ("leaf2", "ethernet-1/1", "client2", "eth1", "lab-access", "cat6"),
        ],
        "wan_circuits": [],
        "tags": ["network-o11y-demo", "clos-lab", "containerlab"],
        "mgmt_defaults": {
            "spine1": "172.20.20.11",
            "leaf1": "172.20.20.12",
            "leaf2": "172.20.20.10",
        },
        "srl_nodes": ("spine1", "leaf1", "leaf2"),
    }


def colocated_topology() -> dict[str, Any]:
    return {
        "sites": [
            {
                "name": "HQ",
                "slug": "hq",
                "description": "Colocated Clos HQ — spine1 + dual leaves + EVPN clients",
                "physical_address": "AWS colocated lab (synthetic HQ)",
            },
            {
                "name": "Branch 1",
                "slug": "branch1",
                "description": "Single-homed branch edge — leaf-br1 + client-br1",
                "physical_address": "AWS colocated lab (synthetic branch 1)",
            },
            {
                "name": "Branch 2",
                "slug": "branch2",
                "description": "Single-homed branch edge — leaf-br2 + client-br2",
                "physical_address": "AWS colocated lab (synthetic branch 2)",
            },
        ],
        "racks": [
            {"name": "HQ Rack 1", "slug": "hq-rack-1", "site": "hq", "u_height": 8, "comments": "HQ Clos — spine, leaves, EVPN clients"},
            {"name": "Branch 1 Rack", "slug": "branch1-rack", "site": "branch1", "u_height": 4, "comments": "Branch 1 edge leaf + client"},
            {"name": "Branch 2 Rack", "slug": "branch2-rack", "site": "branch2", "u_height": 4, "comments": "Branch 2 edge leaf + client"},
        ],
        "roles": [
            {"name": "Spine", "slug": "spine", "color": "2196f3", "vm_role": False},
            {"name": "Leaf", "slug": "leaf", "color": "4caf50", "vm_role": False},
            {"name": "Branch Edge", "slug": "branch-edge", "color": "ff9800", "vm_role": False},
            {"name": "Client", "slug": "client", "color": "9e9e9e", "vm_role": False},
        ],
        "devices": [
            {"name": "spine1", "role": "spine", "type": "7220-ixr-d2l", "site": "hq", "rack": "hq-rack-1", "position": 1, "platform": True},
            {"name": "leaf1", "role": "leaf", "type": "7220-ixr-d2l", "site": "hq", "rack": "hq-rack-1", "position": 2, "platform": True},
            {"name": "leaf2", "role": "leaf", "type": "7220-ixr-d2l", "site": "hq", "rack": "hq-rack-1", "position": 3, "platform": True},
            {"name": "client1", "role": "client", "type": "network-multitool", "site": "hq", "rack": "hq-rack-1", "position": 4, "platform": False},
            {"name": "client2", "role": "client", "type": "network-multitool", "site": "hq", "rack": "hq-rack-1", "position": 5, "platform": False},
            {"name": "leaf-br1", "role": "branch-edge", "type": "7220-ixr-d2l", "site": "branch1", "rack": "branch1-rack", "position": 1, "platform": True},
            {"name": "client-br1", "role": "client", "type": "network-multitool", "site": "branch1", "rack": "branch1-rack", "position": 2, "platform": False},
            {"name": "leaf-br2", "role": "branch-edge", "type": "7220-ixr-d2l", "site": "branch2", "rack": "branch2-rack", "position": 1, "platform": True},
            {"name": "client-br2", "role": "client", "type": "network-multitool", "site": "branch2", "rack": "branch2-rack", "position": 2, "platform": False},
        ],
        "device_live": {
            "spine1": {"serial": "NSRLAB-SPN-001", "asset_tag": "LAB-HQ-U1"},
            "leaf1": {"serial": "NSRLAB-LF-001", "asset_tag": "LAB-HQ-U2"},
            "leaf2": {"serial": "NSRLAB-LF-002", "asset_tag": "LAB-HQ-U3"},
            "client1": {"serial": "LAB-CLT-001", "asset_tag": "LAB-HQ-U4"},
            "client2": {"serial": "LAB-CLT-002", "asset_tag": "LAB-HQ-U5"},
            "leaf-br1": {"serial": "NSRLAB-BR1-001", "asset_tag": "LAB-BR1-U1"},
            "client-br1": {"serial": "LAB-CLT-BR1", "asset_tag": "LAB-BR1-U2"},
            "leaf-br2": {"serial": "NSRLAB-BR2-001", "asset_tag": "LAB-BR2-U1"},
            "client-br2": {"serial": "LAB-CLT-BR2", "asset_tag": "LAB-BR2-U2"},
        },
        "interfaces": [
            ("spine1", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("spine1", "ethernet-1/1", "10gbase-x-sfpp", "HQ fabric to leaf1"),
            ("spine1", "ethernet-1/2", "10gbase-x-sfpp", "HQ fabric to leaf2"),
            ("spine1", "ethernet-1/3", "10gbase-x-sfpp", "WAN to branch1 (leaf-br1)"),
            ("spine1", "ethernet-1/4", "10gbase-x-sfpp", "WAN to branch2 (leaf-br2)"),
            ("leaf1", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("leaf1", "ethernet-1/49", "10gbase-x-sfpp", "Uplink to spine1"),
            ("leaf1", "ethernet-1/1", "10gbase-x-sfpp", "Access to client1"),
            ("leaf2", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("leaf2", "ethernet-1/49", "10gbase-x-sfpp", "Uplink to spine1"),
            ("leaf2", "ethernet-1/1", "10gbase-x-sfpp", "Access to client2"),
            ("leaf-br1", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("leaf-br1", "ethernet-1/49", "10gbase-x-sfpp", "WAN uplink to HQ spine1"),
            ("leaf-br1", "ethernet-1/1", "10gbase-x-sfpp", "Access to client-br1"),
            ("leaf-br2", "mgmt0", "1000base-t", "Management — clab bridge"),
            ("leaf-br2", "ethernet-1/49", "10gbase-x-sfpp", "WAN uplink to HQ spine1"),
            ("leaf-br2", "ethernet-1/1", "10gbase-x-sfpp", "Access to client-br2"),
            ("client1", "eth0", "1000base-t", "Management"),
            ("client1", "eth1", "1000base-t", "EVPN fabric — 172.17.0.1/24"),
            ("client2", "eth0", "1000base-t", "Management"),
            ("client2", "eth1", "1000base-t", "EVPN fabric — 172.17.0.2/24"),
            ("client-br1", "eth0", "1000base-t", "Management"),
            ("client-br1", "eth1", "1000base-t", "Branch LAN — 172.17.21.1/24"),
            ("client-br2", "eth0", "1000base-t", "Management"),
            ("client-br2", "eth1", "1000base-t", "Branch LAN — 172.17.22.1/24"),
        ],
        "prefixes": [
            {"prefix": "172.20.20.0/24", "site": "hq", "description": "ContainerLab mgmt (clab)"},
            {"prefix": "172.17.0.0/24", "site": "hq", "description": "HQ EVPN overlay client subnet"},
            {"prefix": "172.17.21.0/24", "site": "branch1", "description": "Branch 1 client LAN"},
            {"prefix": "172.17.22.0/24", "site": "branch2", "description": "Branch 2 client LAN"},
            {"prefix": "192.168.0.0/16", "site": "hq", "description": "eBGP underlay /31 links (HQ + WAN)"},
        ],
        "client_ips": {
            "client1": ("172.17.0.1/24", "eth1"),
            "client2": ("172.17.0.2/24", "eth1"),
            "client-br1": ("172.17.21.1/24", "eth1"),
            "client-br2": ("172.17.22.1/24", "eth1"),
        },
        "underlay_ips": [
            ("spine1", "ethernet-1/1", "192.168.11.1/31"),
            ("leaf1", "ethernet-1/49", "192.168.11.0/31"),
            ("spine1", "ethernet-1/2", "192.168.21.1/31"),
            ("leaf2", "ethernet-1/49", "192.168.21.0/31"),
            ("spine1", "ethernet-1/3", "192.168.31.1/31"),
            ("leaf-br1", "ethernet-1/49", "192.168.31.0/31"),
            ("spine1", "ethernet-1/4", "192.168.41.1/31"),
            ("leaf-br2", "ethernet-1/49", "192.168.41.0/31"),
        ],
        "cables": [
            ("spine1", "ethernet-1/1", "leaf1", "ethernet-1/49", "lab-fabric", "mmf"),
            ("spine1", "ethernet-1/2", "leaf2", "ethernet-1/49", "lab-fabric", "mmf"),
            ("leaf1", "ethernet-1/1", "client1", "eth1", "lab-access", "cat6"),
            ("leaf2", "ethernet-1/1", "client2", "eth1", "lab-access", "cat6"),
            ("leaf-br1", "ethernet-1/1", "client-br1", "eth1", "lab-access", "cat6"),
            ("leaf-br2", "ethernet-1/1", "client-br2", "eth1", "lab-access", "cat6"),
        ],
        "wan_circuits": [
            {
                "cid": "WAN-HQ-BR1",
                "a_site": "hq",
                "z_site": "branch1",
                "a": ("spine1", "ethernet-1/3"),
                "z": ("leaf-br1", "ethernet-1/49"),
                "description": "HQ spine1 e1-3 <-> branch1 leaf-br1 e1-49",
            },
            {
                "cid": "WAN-HQ-BR2",
                "a_site": "hq",
                "z_site": "branch2",
                "a": ("spine1", "ethernet-1/4"),
                "z": ("leaf-br2", "ethernet-1/49"),
                "description": "HQ spine1 e1-4 <-> branch2 leaf-br2 e1-49",
            },
        ],
        "tags": ["network-o11y-demo", "clos-lab", "containerlab", "colocated", "intended-topology"],
        "mgmt_defaults": {},
        "srl_nodes": ("spine1", "leaf1", "leaf2", "leaf-br1", "leaf-br2"),
    }


def api(base: str, token: str):
    headers = {
        "Authorization": netbox_auth_header(token),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    def req(method: str, path: str, data: dict | None = None):
        url = f"{base.rstrip('/')}/api/{path.lstrip('/')}"
        body = None if data is None else json.dumps(data).encode()
        r = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} {method} {url}: {e.read().decode()}") from e

    def get_list(path: str, **params):
        params = dict(params)
        params.setdefault("limit", 200)
        out: list[dict] = []
        offset = 0
        while True:
            params["offset"] = offset
            qs = urllib.parse.urlencode(params)
            page = req("GET", f"{path}?{qs}")
            results = page.get("results") or []
            out.extend(results)
            if not page.get("next"):
                break
            offset += len(results)
            if not results:
                break
        return out

    def get_or_create(path: str, field: str, data: dict):
        found = get_list(path, **{field: data[field]})
        if found:
            return found[0]
        return req("POST", path, data)

    return req, get_list, get_or_create


def is_loopback(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def resolve_base_url(cli_url: str | None, profile: str) -> str:
    if cli_url:
        return cli_url.rstrip("/")
    public = os.environ.get("NETBOX_PUBLIC_URL", "").strip().rstrip("/")
    host = netbox_url_for_host()
    if public and (is_loopback(host) or profile == "colocated"):
        # Colocated populate from a laptop hits the public NLB, not the SSM tunnel.
        if is_loopback(host):
            return public or PUBLIC_NETBOX
        if profile == "colocated" and public:
            return public
    if is_loopback(host) and profile == "colocated":
        return PUBLIC_NETBOX
    return host.rstrip("/")


def wait_ready(base: str, token: str, retries: int = 12, delay: int = 5) -> None:
    print(f"Waiting for NetBox at {urlparse(base).hostname} ...", flush=True)
    headers = {"Authorization": netbox_auth_header(token), "Accept": "application/json"}
    for i in range(retries):
        try:
            r = urllib.request.Request(f"{base.rstrip('/')}/api/", headers=headers)
            with urllib.request.urlopen(r, timeout=10) as resp:
                if resp.status == 200:
                    print("NetBox is ready.", flush=True)
                    return
        except Exception as exc:
            print(f"  attempt {i + 1}/{retries}: {type(exc).__name__}", flush=True)
        time.sleep(delay)
    sys.exit("NetBox did not become ready in time")


def docker_mgmt_ip(node: str, network: str) -> str | None:
    fmt = f'{{{{(index .NetworkSettings.Networks "{network}").IPAddress}}}}'
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "-f", fmt, node],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not out or out == "<no value>":
        return None
    return out


def ensure_tag(req, get_list, name: str, slug: str) -> int:
    found = get_list("extras/tags/", slug=slug)
    if found:
        return found[0]["id"]
    return req("POST", "extras/tags/", {"name": name, "slug": slug, "color": "9e9e9e"})["id"]


def ensure_ip(req, get_list, address: str, iface_id: int, description: str, device_id: int | None = None) -> dict:
    ip_host = address.split("/")[0]
    for dev in get_list("dcim/devices/"):
        if device_id is not None and dev["id"] == device_id:
            continue
        pri = dev.get("primary_ip4")
        if not pri or not isinstance(pri, dict):
            continue
        if pri.get("address", "").split("/")[0] == ip_host:
            req("PATCH", f"dcim/devices/{dev['id']}/", {"primary_ip4": None})

    existing = get_list("ipam/ip-addresses/", address=address)
    if existing:
        ip_obj = existing[0]
        if ip_obj.get("assigned_object_id") != iface_id:
            req(
                "PATCH",
                f"ipam/ip-addresses/{ip_obj['id']}/",
                {"assigned_object_type": None, "assigned_object_id": None},
            )
            ip_obj = req(
                "PATCH",
                f"ipam/ip-addresses/{ip_obj['id']}/",
                {
                    "assigned_object_type": "dcim.interface",
                    "assigned_object_id": iface_id,
                    "description": description,
                },
            )
        return ip_obj
    return req(
        "POST",
        "ipam/ip-addresses/",
        {
            "address": address,
            "status": "active",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface_id,
            "description": description,
        },
    )


def cable_ids(cable: dict) -> set[int]:
    terms = cable.get("a_terminations", []) + cable.get("b_terminations", [])
    return {t.get("object_id") for t in terms if t.get("object_id") is not None}


def ensure_cable(
    req,
    get_list,
    a_id: int,
    b_id: int,
    *,
    a_type: str = "dcim.interface",
    b_type: str = "dcim.interface",
    label: str = "lab-fabric",
    cable_type: str = "mmf",
) -> None:
    for cable in get_list("dcim/cables/"):
        if a_id in cable_ids(cable) and b_id in cable_ids(cable):
            return
    req(
        "POST",
        "dcim/cables/",
        {
            "status": "connected",
            "type": cable_type,
            "label": label,
            "a_terminations": [{"object_type": a_type, "object_id": a_id}],
            "b_terminations": [{"object_type": b_type, "object_id": b_id}],
        },
    )


def slug_of(obj: dict | None) -> str:
    if not obj:
        return ""
    if isinstance(obj, dict):
        return obj.get("slug") or ""
    return ""


def upsert_device(req, get_list, payload: dict, existing: dict | None) -> dict:
    if not existing:
        return req("POST", "dcim/devices/", payload)
    dev_id = existing["id"]
    cur_site = slug_of(existing.get("site"))
    want_site = payload.get("_site_slug")
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    if existing.get("rack") and want_site and cur_site != want_site:
        req("PATCH", f"dcim/devices/{dev_id}/", {"rack": None, "position": None})
    try:
        return req("PATCH", f"dcim/devices/{dev_id}/", payload)
    except RuntimeError as exc:
        print(f"  retry {payload.get('name')} without rack/asset: {exc}", flush=True)
        slim = {k: v for k, v in payload.items() if k not in {"rack", "position", "face", "asset_tag", "serial"}}
        return req("PATCH", f"dcim/devices/{dev_id}/", slim)


def delete_cable_between(req, get_list, a_id: int, b_id: int) -> None:
    for cable in get_list("dcim/cables/"):
        if a_id in cable_ids(cable) and b_id in cable_ids(cable):
            req("DELETE", f"dcim/cables/{cable['id']}/")


def ensure_termination(req, get_list, circuit_id: int, side: str, site_id: int) -> dict:
    for term in get_list("circuits/circuit-terminations/", circuit_id=circuit_id):
        if term.get("term_side") == side:
            return term
    payloads = [
        {
            "circuit": circuit_id,
            "term_side": side,
            "termination_type": "dcim.site",
            "termination_id": site_id,
        },
        {
            "circuit": circuit_id,
            "term_side": side,
            "termination": {"object_type": "dcim.site", "object_id": site_id},
        },
    ]
    last_err: Exception | None = None
    for payload in payloads:
        try:
            return req("POST", "circuits/circuit-terminations/", payload)
        except RuntimeError as exc:
            last_err = exc
    raise RuntimeError(f"circuit termination {side} failed: {last_err}")


def ensure_wan_circuit(
    req,
    get_list,
    get_or_create,
    circuit: dict,
    site_ids: dict[str, int],
    iface_ids: dict[tuple[str, str], int],
    tenant_id: int,
) -> None:
    provider = get_or_create(
        "circuits/providers/",
        "slug",
        {"name": "Lab WAN", "slug": "lab-wan", "description": "Synthetic WAN for colocated branches"},
    )
    ctype = get_or_create(
        "circuits/circuit-types/",
        "slug",
        {"name": "WAN", "slug": "wan", "description": "Site-to-site WAN"},
    )
    existing = get_list("circuits/circuits/", cid=circuit["cid"])
    if existing:
        circ = existing[0]
    else:
        circ = req(
            "POST",
            "circuits/circuits/",
            {
                "cid": circuit["cid"],
                "provider": provider["id"],
                "type": ctype["id"],
                "status": "active",
                "tenant": tenant_id,
                "description": circuit["description"],
            },
        )
    a_term = ensure_termination(req, get_list, circ["id"], "A", site_ids[circuit["a_site"]])
    z_term = ensure_termination(req, get_list, circ["id"], "Z", site_ids[circuit["z_site"]])
    a_dev, a_if = circuit["a"]
    z_dev, z_if = circuit["z"]
    a_iface = iface_ids[(a_dev, a_if)]
    z_iface = iface_ids[(z_dev, z_if)]
    # Drop the device-device fallback so the WAN ifaces can terminate the circuit.
    delete_cable_between(req, get_list, a_iface, z_iface)
    ensure_cable(
        req,
        get_list,
        a_term["id"],
        a_iface,
        a_type="circuits.circuittermination",
        b_type="dcim.interface",
        label="lab-wan",
        cable_type="smf",
    )
    ensure_cable(
        req,
        get_list,
        z_term["id"],
        z_iface,
        a_type="circuits.circuittermination",
        b_type="dcim.interface",
        label="lab-wan",
        cable_type="smf",
    )


def find_device(get_list, name: str, site_slug: str) -> dict | None:
    matches = get_list("dcim/devices/", name=name)
    if not matches:
        return None
    for m in matches:
        if slug_of(m.get("site")) == site_slug:
            return m
    racked = [m for m in matches if m.get("rack")]
    if racked:
        return racked[0]
    return matches[0]


def prune_name_duplicates(req, get_list, keep_ids: dict[str, int]) -> None:
    """Orb re-creates devices at the discovery site; drop same-name ghosts."""
    for name, keep_id in keep_ids.items():
        for dev in get_list("dcim/devices/", name=name):
            if dev["id"] == keep_id:
                continue
            site = slug_of(dev.get("site")) or "?"
            print(f"  prune duplicate {name} id={dev['id']} site={site}", flush=True)
            req("DELETE", f"dcim/devices/{dev['id']}/")


def tidy_to_topology(req, get_list, topo: dict, device_ids: dict[str, int]) -> None:
    """Keep only intended Clos devices + role-bearing interfaces."""
    keep_names = {d["name"] for d in topo["devices"]}
    keep_ifaces: dict[str, set[str]] = {}
    for dev_name, iface_name, *_rest in topo["interfaces"]:
        keep_ifaces.setdefault(dev_name, set()).add(iface_name)

    def drop_extra_devices() -> int:
        n = 0
        for dev in list(get_list("dcim/devices/")):
            name = dev["name"]
            keep_id = device_ids.get(name)
            extra = name not in keep_names
            ghost = keep_id is not None and dev["id"] != keep_id
            if not extra and not ghost:
                continue
            site = slug_of(dev.get("site")) or "?"
            why = "extra" if extra else "ghost"
            print(f"  tidy delete {why} device {name} id={dev['id']} site={site}", flush=True)
            try:
                req("DELETE", f"dcim/devices/{dev['id']}/")
                n += 1
            except RuntimeError as exc:
                print(f"    skip device: {exc}", flush=True)
        prune_name_duplicates(req, get_list, device_ids)
        return n

    def drop_extra_ifaces() -> int:
        n = 0
        for dev_name, keep in keep_ifaces.items():
            did = device_ids.get(dev_name)
            if not did:
                continue
            seen: dict[str, int] = {}
            ifaces = get_list("dcim/interfaces/", device_id=did)
            ranked = sorted(
                ifaces,
                key=lambda i: (
                    -len(str(i.get("name") or "")),
                    0 if (i.get("cable") or i.get("count_ipaddresses")) else 1,
                    int(i["id"]),
                ),
            )
            for iface in ranked:
                name = iface["name"]
                drop = name not in keep or name in seen
                if not drop:
                    seen[name] = iface["id"]
                    continue
                print(f"  tidy delete iface {dev_name}:{name} id={iface['id']}", flush=True)
                try:
                    req("DELETE", f"dcim/interfaces/{iface['id']}/")
                    n += 1
                except RuntimeError as exc:
                    print(f"    skip iface: {exc}", flush=True)
        return n

    for attempt in range(1, 4):
        gone_dev = drop_extra_devices()
        gone_if = drop_extra_ifaces()
        print(f"  tidy pass {attempt}: devices_removed={gone_dev} ifaces_removed={gone_if}", flush=True)
        if gone_dev == 0 and gone_if == 0:
            break

    leftover_site = None
    for site in get_list("dcim/sites/", slug="network-lab"):
        leftover_site = site
        break
    if leftover_site:
        leftover_devs = [
            d for d in get_list("dcim/devices/") if slug_of(d.get("site")) == "network-lab"
        ]
        if leftover_devs:
            print(
                f"  tidy leave site network-lab ({len(leftover_devs)} devices remain; "
                "Orb is likely still ingesting)",
                flush=True,
            )
        else:
            for rack in get_list("dcim/racks/", site_id=leftover_site["id"]):
                print(f"  tidy delete rack {rack['name']} id={rack['id']}", flush=True)
                try:
                    req("DELETE", f"dcim/racks/{rack['id']}/")
                except RuntimeError as exc:
                    print(f"    skip rack: {exc}", flush=True)
            print(f"  tidy delete empty site network-lab id={leftover_site['id']}", flush=True)
            try:
                req("DELETE", f"dcim/sites/{leftover_site['id']}/")
            except RuntimeError as exc:
                print(f"    skip site: {exc}", flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed NetBox with lab Clos topology")
    p.add_argument(
        "--profile",
        choices=("laptop", "colocated"),
        default="",
        help="Topology to seed (default: LAB_FABRIC_PROFILE or laptop)",
    )
    p.add_argument("--base-url", default="", help="NetBox URL override (skips localhost tunnel)")
    p.add_argument("--skip-circuits", action="store_true", help="Do not create WAN circuit objects")
    p.add_argument(
        "--tidy",
        action="store_true",
        help="Delete Orb ghosts, extra devices, and unused SNMP interfaces",
    )
    p.add_argument(
        "--no-tidy",
        action="store_true",
        help="Keep Orb-discovered extra interfaces (overrides colocated default tidy)",
    )
    p.add_argument(
        "--tidy-only",
        action="store_true",
        help="Only prune extras against the profile topology (no seed/upsert)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv()
    profile = (args.profile or os.environ.get("LAB_FABRIC_PROFILE", "laptop")).strip() or "laptop"
    if profile not in {"laptop", "colocated"}:
        profile = "laptop"
    topo = colocated_topology() if profile == "colocated" else laptop_topology()

    base = resolve_base_url(args.base_url.strip() or None, profile)
    token = os.environ.get("NETBOX_TOKEN", "").strip()
    clab = os.environ.get("CLAB_NETWORK", "clab")
    if not token:
        print("NETBOX_TOKEN is required", file=sys.stderr)
        return 1

    print(f"profile={profile} url_host={urlparse(base).hostname}", flush=True)
    wait_ready(base, token, retries=8 if not is_loopback(base) else 60)
    req, get_list, get_or_create = api(base, token)

    do_tidy = (args.tidy or args.tidy_only or profile == "colocated") and not args.no_tidy

    if args.tidy_only:
        device_ids = {}
        for dev in topo["devices"]:
            found = find_device(get_list, dev["name"], dev["site"])
            if found:
                device_ids[dev["name"]] = found["id"]
            else:
                print(f"  tidy-only missing {dev['name']} site={dev['site']}", flush=True)
        print("tidying to intended Clos ...", flush=True)
        tidy_to_topology(req, get_list, topo, device_ids)
        devices = get_list("dcim/devices/")
        ifaces = get_list("dcim/interfaces/")
        cables = get_list("dcim/cables/")
        print(
            f"Tidied profile={profile} devices={len(devices)} "
            f"ifaces={len(ifaces)} cables={len(cables)}",
            flush=True,
        )
        print(f"NetBox UI: {base}", flush=True)
        return 0

    region = get_or_create("dcim/regions/", "slug", REGION)
    tenant = get_or_create("tenancy/tenants/", "slug", TENANT)
    site_ids: dict[str, int] = {}
    for site in topo["sites"]:
        obj = get_or_create(
            "dcim/sites/",
            "slug",
            {
                "name": site["name"],
                "slug": site["slug"],
                "status": "active",
                "description": site["description"],
                "region": region["id"],
                "physical_address": site.get("physical_address", ""),
            },
        )
        site_ids[site["slug"]] = obj["id"]

    rack_ids: dict[str, int] = {}
    for rack in topo["racks"]:
        obj = get_or_create(
            "dcim/racks/",
            "name",
            {
                "name": rack["name"],
                "slug": rack["slug"],
                "site": site_ids[rack["site"]],
                "tenant": tenant["id"],
                "status": "active",
                "u_height": rack["u_height"],
                "desc_units": True,
                "comments": rack["comments"],
            },
        )
        rack_ids[rack["slug"]] = obj["id"]

    mfr = get_or_create("dcim/manufacturers/", "slug", MANUFACTURER)
    platform = get_or_create(
        "dcim/platforms/",
        "slug",
        {"name": PLATFORM["name"], "slug": PLATFORM["slug"], "manufacturer": mfr["id"]},
    )

    dtype_ids: dict[str, int] = {}
    for dt in DEVICE_TYPES:
        obj = get_or_create(
            "dcim/device-types/",
            "slug",
            {
                "model": dt["model"],
                "slug": dt["slug"],
                "manufacturer": mfr["id"],
                "u_height": dt["u_height"],
            },
        )
        dtype_ids[dt["slug"]] = obj["id"]

    role_ids: dict[str, int] = {}
    for role in topo["roles"]:
        obj = get_or_create("dcim/device-roles/", "slug", role)
        role_ids[role["slug"]] = obj["id"]

    tag_ids = [ensure_tag(req, get_list, t, t) for t in topo["tags"]]

    device_ids: dict[str, int] = {}
    for dev in topo["devices"]:
        meta = topo["device_live"][dev["name"]]
        existing = find_device(get_list, dev["name"], dev["site"])
        existing_tags = []
        if existing:
            existing_tags = [t["id"] if isinstance(t, dict) else t for t in (existing.get("tags") or [])]
        payload = {
            "name": dev["name"],
            "device_type": dtype_ids[dev["type"]],
            "role": role_ids[dev["role"]],
            "site": site_ids[dev["site"]],
            "tenant": tenant["id"],
            "rack": rack_ids[dev["rack"]],
            "position": dev["position"],
            "face": "front",
            "status": "active",
            "serial": meta["serial"],
            "asset_tag": meta["asset_tag"],
            "comments": live_comment(dev["role"], dev["name"]),
            "tags": list({*existing_tags, *tag_ids}),
            "_site_slug": dev["site"],
        }
        if dev["platform"]:
            payload["platform"] = platform["id"]
        obj = upsert_device(req, get_list, payload, existing)
        device_ids[dev["name"]] = obj["id"]
        print(f"  device {dev['name']} role={dev['role']} site={dev['site']}", flush=True)

    prune_name_duplicates(req, get_list, device_ids)

    iface_ids: dict[tuple[str, str], int] = {}
    for dev_name, iface_name, iface_type, description in topo["interfaces"]:
        dev_id = device_ids[dev_name]
        existing = get_list("dcim/interfaces/", device_id=dev_id, name=iface_name)
        patch = {"description": description, "enabled": True}
        if existing:
            try:
                obj = req("PATCH", f"dcim/interfaces/{existing[0]['id']}/", {**patch, "type": iface_type})
            except RuntimeError:
                obj = req("PATCH", f"dcim/interfaces/{existing[0]['id']}/", patch)
        else:
            obj = req(
                "POST",
                "dcim/interfaces/",
                {
                    "device": dev_id,
                    "name": iface_name,
                    "type": iface_type,
                    "description": description,
                    "enabled": True,
                },
            )
        iface_ids[(dev_name, iface_name)] = obj["id"]

    for pf in topo["prefixes"]:
        existing = get_list("ipam/prefixes/", prefix=pf["prefix"])
        if not existing:
            req(
                "POST",
                "ipam/prefixes/",
                {
                    "prefix": pf["prefix"],
                    "site": site_ids[pf["site"]],
                    "tenant": tenant["id"],
                    "status": "active",
                    "description": pf["description"],
                },
            )

    for dev_name, iface_name, address in topo["underlay_ips"]:
        ensure_ip(
            req,
            get_list,
            address,
            iface_ids[(dev_name, iface_name)],
            f"{dev_name} underlay",
            device_id=device_ids[dev_name],
        )

    for client, (ip, iface_name) in topo["client_ips"].items():
        ip_obj = ensure_ip(
            req,
            get_list,
            ip,
            iface_ids[(client, iface_name)],
            f"{client} overlay/LAN",
            device_id=device_ids[client],
        )
        req("PATCH", f"dcim/devices/{device_ids[client]}/", {"primary_ip4": ip_obj["id"]})

    for a_dev, a_if, b_dev, b_if, label, cable_type in topo["cables"]:
        ensure_cable(
            req,
            get_list,
            iface_ids[(a_dev, a_if)],
            iface_ids[(b_dev, b_if)],
            label=label,
            cable_type=cable_type,
        )
        print(f"  cable {label} {a_dev}:{a_if} <-> {b_dev}:{b_if}", flush=True)

    if not args.skip_circuits:
        for circuit in topo["wan_circuits"]:
            try:
                ensure_wan_circuit(req, get_list, get_or_create, circuit, site_ids, iface_ids, tenant["id"])
                print(f"  circuit {circuit['cid']}", flush=True)
            except RuntimeError as exc:
                print(f"  circuit {circuit['cid']} failed, fallback cable: {exc}", flush=True)
                a_dev, a_if = circuit["a"]
                z_dev, z_if = circuit["z"]
                ensure_cable(
                    req,
                    get_list,
                    iface_ids[(a_dev, a_if)],
                    iface_ids[(z_dev, z_if)],
                    label="lab-wan",
                    cable_type="smf",
                )

    for node in topo["srl_nodes"]:
        live_ip = docker_mgmt_ip(node, clab) or topo["mgmt_defaults"].get(node)
        if not live_ip:
            continue
        if (node, "mgmt0") not in iface_ids:
            continue
        cidr = f"{live_ip}/32"
        src = "clab" if docker_mgmt_ip(node, clab) else "default"
        print(f"{node} mgmt → {cidr} ({src})", flush=True)
        ip_obj = ensure_ip(
            req,
            get_list,
            cidr,
            iface_ids[(node, "mgmt0")],
            f"{node} mgmt ({src})",
            device_id=device_ids[node],
        )
        req("PATCH", f"dcim/devices/{device_ids[node]}/", {"primary_ip4": ip_obj["id"]})

    prune_name_duplicates(req, get_list, device_ids)
    if do_tidy:
        print("tidying to intended Clos ...", flush=True)
        tidy_to_topology(req, get_list, topo, device_ids)

    devices = get_list("dcim/devices/")
    cables = get_list("dcim/cables/")
    prefixes = get_list("ipam/prefixes/")
    ifaces = get_list("dcim/interfaces/")
    print(
        f"Populated profile={profile} devices={len(devices)} ifaces={len(ifaces)} "
        f"cables={len(cables)} prefixes={len(prefixes)}",
        flush=True,
    )
    print(f"NetBox UI: {base}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
