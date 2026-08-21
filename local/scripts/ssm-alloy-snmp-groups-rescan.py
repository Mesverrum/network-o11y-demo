#!/usr/bin/env python3
"""Clear discovery state and rescan so leftover colocated groups are gone."""
from __future__ import annotations

import json
import pathlib
import subprocess
import time

IID = "i-0639d827b3ecf3b82"
REPO = pathlib.Path(__file__).resolve().parents[2]


def main() -> None:
    params_path = REPO / "local" / ".ssm-alloy-cutover-snmp-rescan.json"
    commands = [
        "set -euo pipefail",
        "export LAB_FABRIC_PROFILE=colocated",
        "cd /opt/network-o11y-demo/local",
        "rm -f alloy/snmp-targets.yml.state.json alloy/*.state.json",
        "echo '==> leaf1'",
        "docker inspect -f '{{.State.Status}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' leaf1 || true",
        "bash scripts/alloy-snmp-discover.sh",
        "echo '==> targets'",
        "grep -E 'snmp_group:|device_name:|^- name:' alloy/snmp-targets.yml || true",
        "echo '==> cold groups'",
        "grep -E 'snmp_group:|device_name:' alloy/snmp-targets-cold.yml || true",
    ]
    params_path.write_text(json.dumps({"commands": commands}), encoding="utf-8")
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
            "240",
            "--parameters",
            f"file://{params_path.as_posix()}",
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ],
        text=True,
    ).strip()
    print("command", cmd_id, flush=True)
    out_path = REPO / "local" / ".ssm-last-out.txt"
    for _ in range(50):
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
        st = inv.get("Status")
        print(f"status={st}", flush=True)
        if st in {"Success", "Failed", "Cancelled", "TimedOut"}:
            out = (inv.get("StandardOutputContent") or "") + "\n--- stderr ---\n" + (inv.get("StandardErrorContent") or "")
            out_path.write_text(out, encoding="utf-8")
            print(out[-4000:])
            raise SystemExit(0 if st == "Success" else 1)
        time.sleep(5)
    raise SystemExit("timeout")


if __name__ == "__main__":
    main()
