#!/usr/bin/env python3
"""Write alloy/device-join.yml = SNMP catalog + fabric clients (join-only).

SNMP scrape keeps snmp-targets.yml (switches only). Traps/syslog/netflow join
this superset so softflowd sampler IPs (client mgmt) and EVPN 172.17.x
conversation IPs stamp device_name / src_device / dst_device.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "alloy" / "device-join.yml"
SNMP = ROOT / "alloy" / "snmp-targets.yml"
CLAB_NET = "clab"


def sh(*args: str) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def load_dotenv() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def fabric_clients(profile: str) -> list[str]:
    if profile == "snmp-min":
        return []
    if profile == "colocated":
        return ["client1", "client2", "client-br1", "client-br2"]
    return ["client1", "client2"]


def fabric_site(name: str) -> str:
    if name in {"spine1", "leaf1", "leaf2", "client1", "client2"}:
        return "hq"
    if name in {"leaf-br1", "client-br1"}:
        return "branch1"
    if name in {"leaf-br2", "client-br2"}:
        return "branch2"
    return "hq"


def node_mgmt(name: str, clab_net: str) -> str:
    tmpl = f"{{{{(index .NetworkSettings.Networks \"{clab_net}\").IPAddress}}}}"
    return sh("docker", "inspect", "-f", tmpl, name)


def node_data_ips(name: str) -> list[str]:
    raw = sh(
        "docker",
        "exec",
        name,
        "sh",
        "-c",
        "ip -o addr show dev eth1 2>/dev/null | awk '{print $4}'",
    )
    out: list[str] = []
    for tok in raw.split():
        ip = tok.split("/", 1)[0].strip()
        if ip and not ip.startswith("fe80:"):
            out.append(ip)
    return out


def yaml_escape(s: str) -> str:
    if any(c in s for c in ":#{}[]&*?|>!%@`"):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def main() -> int:
    env = load_dotenv()
    profile = env.get("LAB_FABRIC_PROFILE", "laptop")
    clab_net = env.get("CLAB_NETWORK", CLAB_NET)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    snmp_body = ""
    if SNMP.is_file():
        snmp_body = SNMP.read_text(encoding="utf-8").strip()
    if snmp_body in ("", "[]", "null"):
        snmp_body = ""

    have_names: set[str] = set()
    for line in snmp_body.splitlines():
        s = line.strip()
        if s.startswith("device_name:"):
            have_names.add(s.split(":", 1)[1].strip().strip("'\""))
        if s.startswith("name:"):
            have_names.add(s.split(":", 1)[1].strip().strip("'\""))

    extra: list[str] = []
    for name in fabric_clients(profile):
        if name in have_names:
            continue
        mgmt = node_mgmt(name, clab_net)
        if not mgmt or mgmt == "<no value>":
            print(f"skip {name}: no clab IP", file=sys.stderr)
            continue
        aliases = node_data_ips(name)
        alias_csv = ",".join(aliases)
        block = [
            f"- name: {yaml_escape(name)}",
            f"  address: {yaml_escape(mgmt)}",
            f"  device_name: {yaml_escape(name)}",
            f"  snmp_group: {fabric_site(name)}",
        ]
        if alias_csv:
            block.append(f"  snmp_aliases: {yaml_escape(alias_csv)}")
        extra.append("\n".join(block))
        print(f"join {name} address={mgmt} aliases={alias_csv or '-'}")

    parts: list[str] = []
    if snmp_body:
        parts.append(snmp_body.rstrip())
    parts.extend(extra)
    text = "\n".join(parts).rstrip() + "\n" if parts else "[]\n"
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({1 + text.count(chr(10) + '- name:')} identities)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
