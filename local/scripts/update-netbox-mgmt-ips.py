#!/usr/bin/env python3
"""Sync ContainerLab mgmt IPs into NetBox primary_ip4 for spine/leaf devices."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from lab_env import load_dotenv, netbox_url_for_host

NODES = ("spine1", "leaf1", "leaf2")
MGMT_IFACE = "mgmt0"


def docker_ip(node: str, network: str) -> str:
    fmt = f"{{{{(index .NetworkSettings.Networks \"{network}\").IPAddress}}}}"
    out = subprocess.check_output(
        ["docker", "inspect", "-f", fmt, node],
        text=True,
    ).strip()
    if not out or out == "<no value>":
        raise RuntimeError(f"no mgmt IP for {node} on {network}")
    return out


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
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}

    def get_list(path: str, **params):
        params["limit"] = 50
        qs = urllib.parse.urlencode(params)
        return req("GET", f"{path}?{qs}")["results"]

    return req, get_list


def main() -> int:
    load_dotenv()
    base = netbox_url_for_host()
    token = os.environ.get("NETBOX_TOKEN", "").strip()
    clab = os.environ.get("CLAB_NETWORK", "clab")
    if not token:
        print("NETBOX_TOKEN is required", file=sys.stderr)
        return 1

    req, get_list = api(base, token)

    for node in NODES:
        ip = docker_ip(node, clab)
        cidr = f"{ip}/32"
        print(f"{node} mgmt → {cidr}")

        devices = get_list("dcim/devices/", name=node)
        if not devices:
            print(f"  skip: device {node} not in NetBox", file=sys.stderr)
            continue
        dev = devices[0]
        dev_id = dev["id"]

        ifaces = get_list("dcim/interfaces/", device_id=dev_id, name=MGMT_IFACE)
        if not ifaces:
            ifaces = [
                req(
                    "POST",
                    "dcim/interfaces/",
                    {
                        "device": dev_id,
                        "name": MGMT_IFACE,
                        "type": "1000base-t",
                        "description": "ContainerLab mgmt",
                    },
                )
            ]
        iface_id = ifaces[0]["id"]

        # Clear stale primary_ip4 on other devices if they claim this /32.
        for other in get_list("dcim/devices/"):
            if other["id"] == dev_id:
                continue
            pri = other.get("primary_ip4")
            if not pri or not isinstance(pri, dict):
                continue
            if pri.get("address", "").split("/")[0] == ip:
                req("PATCH", f"dcim/devices/{other['id']}/", {"primary_ip4": None})

        existing = get_list("ipam/ip-addresses/", address=cidr)
        if existing:
            ip_obj = existing[0]
            if ip_obj.get("assigned_object_id") != iface_id:
                # Unassign from wrong interface before re-binding.
                req(
                    "PATCH",
                    f"ipam/ip-addresses/{ip_obj['id']}/",
                    {
                        "assigned_object_type": None,
                        "assigned_object_id": None,
                    },
                )
                ip_obj = req(
                    "PATCH",
                    f"ipam/ip-addresses/{ip_obj['id']}/",
                    {
                        "assigned_object_type": "dcim.interface",
                        "assigned_object_id": iface_id,
                    },
                )
        else:
            ip_obj = req(
                "POST",
                "ipam/ip-addresses/",
                {
                    "address": cidr,
                    "status": "active",
                    "assigned_object_type": "dcim.interface",
                    "assigned_object_id": iface_id,
                    "description": f"{node} clab mgmt",
                },
            )

        pri = dev.get("primary_ip4")
        pri_id = pri.get("id") if isinstance(pri, dict) else pri
        if pri_id != ip_obj["id"]:
            req("PATCH", f"dcim/devices/{dev_id}/", {"primary_ip4": ip_obj["id"]})
        print(f"  updated primary_ip4 for {node}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
