#!/usr/bin/env python3
"""Recover fabric + CIDR discovery after clab IP drift or SRL exit."""
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], check: bool = False, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, check=check, **kw)


def clab_ips() -> dict[str, str]:
    out = run(
        ["bash", "scripts/clab.sh", "inspect", "--format", "json"],
        capture_output=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr or "clab inspect failed")
    data = json.loads(out.stdout)
    rows = data.get("srl-local", data) if isinstance(data, dict) else data
    ips: dict[str, str] = {}
    for c in rows:
        name = c.get("name", "")
        addr = c.get("ipv4_address", "")
        if addr and addr != "N/A" and name in ("spine1", "leaf1", "leaf2"):
            ips[name] = addr.split("/")[0]
    return ips


def main() -> int:
    print("==> stopping telemetry compose (free RAM for SRL)")
    run(
        [
            "docker",
            "compose",
            "-f",
            "compose-base.yaml",
            "-f",
            "compose-groups.generated.yaml",
            "-f",
            "compose-catalog.generated.yaml",
            "stop",
        ],
        check=False,
    )

    print("==> redeploying fabric")
    redeploy = run(["bash", "scripts/clab.sh", "deploy", "--reconfigure"])
    if redeploy.returncode != 0:
        return redeploy.returncode

    print("==> waiting 90s for SR Linux")
    time.sleep(90)

    ips = clab_ips()
    missing = [n for n in ("spine1", "leaf1", "leaf2") if n not in ips]
    if missing:
        print("ERROR: still missing mgmt IPs for:", ", ".join(missing))
        run(["bash", "scripts/clab.sh", "inspect"])
        return 1

    for n, ip in ips.items():
        if n in ("spine1", "leaf1", "leaf2"):
            print(f"  {n} -> {ip}")

    print("==> apply fabric + SNMP")
    fab = run(["bash", "scripts/apply-fabric-config.sh"])
    if fab.returncode != 0:
        print("WARNING: apply-fabric-config returned", fab.returncode)

    joined = ",".join(f"{ips[n]}/32" for n in ("spine1", "leaf1", "leaf2"))
    env = ROOT / "groups" / "srl.env"
    text = env.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^DISCOVERY_SOURCE=.*$", "DISCOVERY_SOURCE=cidr", text, count=1)
    text = re.sub(r"(?m)^TARGETS=.*$", f"TARGETS={joined}", text, count=1)
    env.write_text(text, encoding="utf-8")
    print(f"==> TARGETS={joined}")

    run(["make", "generate"], check=True)

    print("==> starting telemetry compose")
    up = run(
        [
            "docker",
            "compose",
            "-f",
            "compose-base.yaml",
            "-f",
            "compose-groups.generated.yaml",
            "-f",
            "compose-catalog.generated.yaml",
            "-f",
            "compose-limits.generated.yaml",
            "up",
            "-d",
        ],
    )
    if up.returncode != 0:
        return up.returncode

    disc = run(["make", "discover", "GROUP=srl"])
    if disc.returncode != 0:
        return disc.returncode

    run(["bash", "scripts/update-topology-targets.sh"])
    run(["bash", "scripts/softflowd.sh"])
    run(["bash", "scripts/syslog-config.sh"])
    run(["bash", "scripts/snmp-trap-config.sh"])
    run(["bash", "scripts/sflow-config.sh"])
    run(["make", "traffic"])
    run(["bash", "scripts/fabric-watch.sh", "start"])
    run(["make", "status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
