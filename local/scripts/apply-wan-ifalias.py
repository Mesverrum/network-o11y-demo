#!/usr/bin/env python3
"""Apply WAN ifAlias descriptions on live SRL lab nodes."""
from __future__ import annotations

import subprocess

UPDATES = [
    ("leaf1", "ethernet-1/49", "WAN uplink to spine"),
    ("leaf2", "ethernet-1/49", "WAN uplink to spine"),
    ("spine1", "ethernet-1/1", "WAN downlink leaf1"),
    ("spine1", "ethernet-1/2", "WAN downlink leaf2"),
]


def apply(node: str, iface: str, desc: str) -> None:
    cfg = f'set / interface {iface} description "{desc}"\ncommit stay\n'
    subprocess.run(
        ["docker", "exec", "-i", node, "bash", "-c", "sr_cli -ed"],
        input=cfg,
        text=True,
        check=True,
    )
    print(f"OK {node} {iface} -> {desc}")


def main() -> int:
    for node, iface, desc in UPDATES:
        apply(node, iface, desc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
