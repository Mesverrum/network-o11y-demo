#!/usr/bin/env python3
"""SNMP walk SRL memory + ifAlias (lab nodes on clab)."""
from __future__ import annotations

import json
import subprocess
import sys

COMM = "public"
NET = "clab"
NODES = ("spine1", "leaf1", "leaf2")
MEM_OIDS = [
    ("sgiCpuUsage", "1.3.6.1.4.1.6527.3.1.2.1.1.1.0"),
    ("sgiKbMemoryUsed", "1.3.6.1.4.1.6527.3.1.2.1.1.9.0"),
    ("sgiKbMemoryAvailable", "1.3.6.1.4.1.6527.3.1.2.1.1.10.0"),
]
HR_MEM = "1.3.6.1.2.1.25.2.3.1"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e:
        return e.output or str(e)


def node_ip(name: str) -> str | None:
    fmt = f"{{{{(index .NetworkSettings.Networks \"{NET}\").IPAddress}}}}"
    out = run(["docker", "inspect", "-f", fmt, name]).strip()
    return out if out and out != "<no value>" else None


def main() -> int:
    for node in NODES:
        ip = node_ip(node)
        print(f"\n======== {node} ({ip or 'missing'}) ========")
        if not ip:
            continue
        print("-- TIMETRA memory --")
        for label, oid in MEM_OIDS:
            line = run(["snmpget", "-v2c", "-c", COMM, "-On", ip, oid]).strip()
            print(f"  {label}: {line or '(no response)'}")
        print("-- HOST-RESOURCES (first rows) --")
        hr = run(["snmpwalk", "-v2c", "-c", COMM, "-On", ip, HR_MEM])
        for line in hr.splitlines()[:6]:
            print(f"  {line}")
        print("-- ifAlias / ifDescr / ifName --")
        for label, oid in (("ifAlias", IF_ALIAS), ("ifDescr", IF_DESCR), ("ifName", IF_NAME)):
            out = run(["snmpwalk", "-v2c", "-c", COMM, "-On", ip, oid])
            lines = [
                ln
                for ln in out.splitlines()
                if ln.strip() and "No Such" not in ln and "No more" not in ln
            ]
            print(f"  [{label}] {len(lines)} rows")
            for line in lines[:8]:
                print(f"    {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
