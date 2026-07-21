#!/usr/bin/env python3
"""Populate NetBox with the local ContainerLab Clos topology (idempotent)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from lab_env import load_dotenv, netbox_url_for_host

SITE = {
    "name": "Network Lab",
    "slug": "network-lab",
    "status": "active",
    "description": "WSL ContainerLab Clos — network-o11y-demo local path",
}
REGION = {"name": "Lab Region", "slug": "lab-region", "description": "Synthetic region for demo inventory"}
TENANT = {"name": "Network O11y Demo", "slug": "network-o11y-demo"}
MANUFACTURER = {"name": "Nokia", "slug": "nokia"}
PLATFORM = {"name": "SR Linux", "slug": "sr-linux"}
ROLES = [
    {"name": "Spine", "slug": "spine", "color": "2196f3", "vm_role": False},
    {"name": "Leaf", "slug": "leaf", "color": "4caf50", "vm_role": False},
    {"name": "Client", "slug": "client", "color": "9e9e9e", "vm_role": False},
]
DEVICE_TYPES = [
    {"model": "7220 IXR-D2L", "slug": "7220-ixr-d2l", "u_height": 1},
    {"model": "network-multitool", "slug": "network-multitool", "u_height": 1},
]
DEVICES = [
    {"name": "spine1", "role": "spine", "type": "7220-ixr-d2l", "position": 1, "platform": True},
    {"name": "leaf1", "role": "leaf", "type": "7220-ixr-d2l", "position": 2, "platform": True},
    {"name": "leaf2", "role": "leaf", "type": "7220-ixr-d2l", "position": 3, "platform": True},
    {"name": "client1", "role": "client", "type": "network-multitool", "position": 4, "platform": False},
    {"name": "client2", "role": "client", "type": "network-multitool", "position": 5, "platform": False},
]
INTERFACES = [
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
]
PREFIXES = [
    {"prefix": "172.20.20.0/24", "description": "ContainerLab mgmt (clab)"},
    {"prefix": "172.17.0.0/24", "description": "EVPN overlay client subnet"},
    {"prefix": "192.168.0.0/16", "description": "eBGP underlay /31 links"},
]
CLIENT_IPS = {
    "client1": ("172.17.0.1/24", "eth1"),
    "client2": ("172.17.0.2/24", "eth1"),
}
UNDERLAY_IPS = [
    ("spine1", "ethernet-1/1", "192.168.11.1/31"),
    ("leaf1", "ethernet-1/49", "192.168.11.0/31"),
    ("spine1", "ethernet-1/2", "192.168.21.1/31"),
    ("leaf2", "ethernet-1/49", "192.168.21.0/31"),
]
CABLES = [
    ("spine1", "ethernet-1/1", "leaf1", "ethernet-1/49"),
    ("spine1", "ethernet-1/2", "leaf2", "ethernet-1/49"),
    ("leaf1", "ethernet-1/1", "client1", "eth1"),
    ("leaf2", "ethernet-1/1", "client2", "eth1"),
]
TAGS = ["network-o11y-demo", "clos-lab", "containerlab"]
# Fallback mgmt /32s when clab nodes are not running (typical clab addressing).
DEFAULT_MGMT_IPS = {
    "spine1": "172.20.20.11",
    "leaf1": "172.20.20.12",
    "leaf2": "172.20.20.10",
}
SRL_NODES = ("spine1", "leaf1", "leaf2")


def live_comment(role: str, name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"network-o11y-demo local lab | role={role} | "
        f"last_inventory_sync={ts} | source=netbox-populate.py"
    )


DEVICE_LIVE = {
    "spine1": {
        "serial": "NSRLAB-SPN-001",
        "asset_tag": "LAB-RACK1-U1",
        "comments": live_comment("spine", "spine1"),
    },
    "leaf1": {
        "serial": "NSRLAB-LF-001",
        "asset_tag": "LAB-RACK1-U2",
        "comments": live_comment("leaf", "leaf1"),
    },
    "leaf2": {
        "serial": "NSRLAB-LF-002",
        "asset_tag": "LAB-RACK1-U3",
        "comments": live_comment("leaf", "leaf2"),
    },
    "client1": {
        "serial": "LAB-CLT-001",
        "asset_tag": "LAB-RACK1-U4",
        "comments": live_comment("client", "client1"),
    },
    "client2": {
        "serial": "LAB-CLT-002",
        "asset_tag": "LAB-RACK1-U5",
        "comments": live_comment("client", "client2"),
    },
}


def api(base: str, token: str):
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    def req(method: str, path: str, data: dict | None = None):
        url = f"{base.rstrip('/')}/api/{path.lstrip('/')}"
        body = None if data is None else json.dumps(data).encode()
        r = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} {method} {url}: {e.read().decode()}") from e

    def get_list(path: str, **params):
        params["limit"] = 200
        qs = urllib.parse.urlencode(params)
        return req("GET", f"{path}?{qs}")["results"]

    def get_or_create(path: str, field: str, data: dict):
        found = get_list(path, **{field: data[field]})
        if found:
            return found[0]
        return req("POST", path, data)

    return req, get_list, get_or_create


def wait_ready(base: str, token: str, retries: int = 60, delay: int = 5) -> None:
    print(f"Waiting for NetBox at {base} ...", flush=True)
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    for i in range(retries):
        try:
            r = urllib.request.Request(f"{base.rstrip('/')}/api/", headers=headers)
            with urllib.request.urlopen(r, timeout=10) as resp:
                if resp.status == 200:
                    print("NetBox is ready.", flush=True)
                    return
        except Exception as exc:
            print(f"  attempt {i + 1}/{retries}: {exc}", flush=True)
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
    # Clear primary_ip4 on other devices that claim this address.
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


def ensure_cable(req, get_list, a_id: int, b_id: int) -> None:
    for cable in get_list("dcim/cables/"):
        terms = cable.get("a_terminations", []) + cable.get("b_terminations", [])
        ids = {t.get("object_id") for t in terms if t.get("object_type") == "dcim.interface"}
        if a_id in ids and b_id in ids:
            return
    req(
        "POST",
        "dcim/cables/",
        {
            "status": "connected",
            "type": "mmf",
            "label": "lab-fabric",
            "a_terminations": [{"object_type": "dcim.interface", "object_id": a_id}],
            "b_terminations": [{"object_type": "dcim.interface", "object_id": b_id}],
        },
    )


def main() -> int:
    load_dotenv()
    base = netbox_url_for_host()
    token = os.environ.get("NETBOX_TOKEN", "").strip()
    clab = os.environ.get("CLAB_NETWORK", "clab")
    if not token:
        print("NETBOX_TOKEN is required", file=sys.stderr)
        return 1

    wait_ready(base, token)
    req, get_list, get_or_create = api(base, token)

    region = get_or_create("dcim/regions/", "slug", REGION)
    site = get_or_create(
        "dcim/sites/",
        "slug",
        {**SITE, "region": region["id"], "physical_address": "WSL2 ContainerLab (synthetic)"},
    )
    tenant = get_or_create("tenancy/tenants/", "slug", TENANT)
    rack = get_or_create(
        "dcim/racks/",
        "name",
        {
            "name": "Lab Rack 1",
            "slug": "lab-rack-1",
            "site": site["id"],
            "tenant": tenant["id"],
            "status": "active",
            "u_height": 8,
            "desc_units": True,
            "comments": "Clos demo rack — spine + leaves + EVPN clients",
        },
    )
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
    for role in ROLES:
        obj = get_or_create("dcim/device-roles/", "slug", role)
        role_ids[role["slug"]] = obj["id"]

    tag_ids = [ensure_tag(req, get_list, t, t) for t in TAGS]

    device_ids: dict[str, int] = {}
    for dev in DEVICES:
        meta = DEVICE_LIVE[dev["name"]]
        payload = {
            "name": dev["name"],
            "device_type": dtype_ids[dev["type"]],
            "role": role_ids[dev["role"]],
            "site": site["id"],
            "tenant": tenant["id"],
            "rack": rack["id"],
            "position": dev["position"],
            "face": "front",
            "status": "active",
            "serial": meta["serial"],
            "asset_tag": meta["asset_tag"],
            "comments": meta["comments"],
            "tags": tag_ids,
        }
        if dev["platform"]:
            payload["platform"] = platform["id"]
        existing = get_list("dcim/devices/", name=dev["name"])
        if existing:
            obj = req("PATCH", f"dcim/devices/{existing[0]['id']}/", payload)
        else:
            obj = req("POST", "dcim/devices/", payload)
        device_ids[dev["name"]] = obj["id"]

    iface_ids: dict[tuple[str, str], int] = {}
    for dev_name, iface_name, iface_type, description in INTERFACES:
        dev_id = device_ids[dev_name]
        existing = get_list("dcim/interfaces/", device_id=dev_id, name=iface_name)
        if existing:
            obj = req(
                "PATCH",
                f"dcim/interfaces/{existing[0]['id']}/",
                {"type": iface_type, "description": description, "enabled": True},
            )
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

    for dev_name, iface_name, address in UNDERLAY_IPS:
        ensure_ip(
            req,
            get_list,
            address,
            iface_ids[(dev_name, iface_name)],
            f"{dev_name} underlay",
        )

    for client, (ip, iface_name) in CLIENT_IPS.items():
        ip_obj = ensure_ip(
            req,
            get_list,
            ip,
            iface_ids[(client, iface_name)],
            f"{client} EVPN fabric",
        )
        req("PATCH", f"dcim/devices/{device_ids[client]}/", {"primary_ip4": ip_obj["id"]})

    for a_dev, a_if, b_dev, b_if in CABLES:
        ensure_cable(
            req,
            get_list,
            iface_ids[(a_dev, a_if)],
            iface_ids[(b_dev, b_if)],
        )

    for node in SRL_NODES:
        live_ip = docker_mgmt_ip(node, clab) or DEFAULT_MGMT_IPS.get(node)
        if not live_ip:
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

    for pf in PREFIXES:
        existing = get_list("ipam/prefixes/", prefix=pf["prefix"])
        if not existing:
            req(
                "POST",
                "ipam/prefixes/",
                {
                    "prefix": pf["prefix"],
                    "site": site["id"],
                    "tenant": tenant["id"],
                    "status": "active",
                    "description": pf["description"],
                },
            )

    ui = os.environ.get("NETBOX_HOST_URL") or base
    print(f"Populated {len(DEVICES)} devices (site={SITE['slug']}).", flush=True)
    print(f"NetBox UI: {ui}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
