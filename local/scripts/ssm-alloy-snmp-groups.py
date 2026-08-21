#!/usr/bin/env python3
"""Sync alloy-snmp-discover.sh and re-run site-chunked discovery on colocated."""
from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import time

IID = "i-0639d827b3ecf3b82"
REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "local" / "scripts" / "alloy-snmp-discover.sh"


def send(commands: list[str], timeout: int, label: str) -> None:
    params_path = REPO / "local" / f".ssm-alloy-cutover-{label}.json"
    params_path.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    print(f"wrote {params_path} ({params_path.stat().st_size} bytes)", flush=True)
    cmd_id = subprocess.check_output(
        [
            "aws",
            "ssm",
            "send-command",
            "--profile",
            "mvr",
            "--region",
            "us-east-1",
            "--instance-ids",
            IID,
            "--document-name",
            "AWS-RunShellScript",
            "--timeout-seconds",
            str(timeout),
            "--parameters",
            f"file://{params_path.as_posix()}",
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ],
        text=True,
    ).strip()
    print(f"{label} command {cmd_id}", flush=True)
    out_path = REPO / "local" / ".ssm-last-out.txt"
    for _ in range(timeout // 5 + 10):
        raw = subprocess.check_output(
            [
                "aws",
                "ssm",
                "get-command-invocation",
                "--profile",
                "mvr",
                "--region",
                "us-east-1",
                "--command-id",
                cmd_id,
                "--instance-id",
                IID,
                "--output",
                "json",
            ],
            text=True,
        )
        inv = json.loads(raw)
        status = inv.get("Status")
        stdout = inv.get("StandardOutputContent") or ""
        stderr = inv.get("StandardErrorContent") or ""
        out_path.write_text(stdout + "\n--- stderr ---\n" + stderr, encoding="utf-8")
        print(f"{label} status={status}", flush=True)
        if status in {"Success", "Failed", "Cancelled", "TimedOut"}:
            print(stdout[-5000:] if stdout else "(no stdout)")
            if stderr:
                print("STDERR:", stderr[-2000:])
            if status != "Success":
                raise SystemExit(1)
            return
        time.sleep(5)
    raise SystemExit(f"timed out waiting for SSM {label}")


def main() -> None:
    dest = "/opt/network-o11y-demo/local/scripts/alloy-snmp-discover.sh"
    b64 = base64.b64encode(SCRIPT.read_bytes()).decode()
    send(
        [
            "set -euo pipefail",
            f'mkdir -p "$(dirname "{dest}")"',
            f'echo {b64} | base64 -d > "{dest}"',
            f'chmod +x "{dest}"',
            f"sed -i 's/\\r$//' \"{dest}\"",
            "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
            "export LAB_FABRIC_PROFILE=colocated",
            "cd /opt/network-o11y-demo/local",
            "bash scripts/alloy-snmp-discover.sh",
            "echo '==> discovery.yml groups'",
            "grep -E 'name:|/' alloy/snmp-discovery.yml || true",
            "echo '==> targets (group / name / address)'",
            "grep -E 'snmp_group:|device_name:|^- name:|address:' alloy/snmp-targets.yml || true",
        ],
        240,
        "snmp-groups",
    )


if __name__ == "__main__":
    main()
