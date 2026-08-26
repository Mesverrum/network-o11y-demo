#!/usr/bin/env python3
"""Inject or clear the webinar Clos fault on colocated EC2 (leaf1 ethernet-1/1)."""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import time

IID = "i-0639d827b3ecf3b82"
REPO = pathlib.Path(__file__).resolve().parents[2]
REL = "local/scripts/workshop-inject-fault.sh"


def send(commands: list[str], timeout: int, label: str) -> None:
    params_path = REPO / "local" / f".ssm-workshop-fault-{label}.json"
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
    out_path = REPO / "local" / ".ssm-workshop-fault-out.txt"
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
                print("STDERR:", stderr[-2500:])
            if status != "Success":
                raise SystemExit(1)
            return
        time.sleep(5)
    raise SystemExit(f"timed out waiting for SSM {label}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "status"))
    args = parser.parse_args()
    src = REPO / REL
    if not src.is_file():
        raise SystemExit(f"missing {src}")
    dest = f"/opt/network-o11y-demo/{REL}"
    b64 = base64.b64encode(src.read_bytes()).decode()
    send(
        [
            "set -euo pipefail",
            f'mkdir -p "$(dirname "{dest}")"',
            f'echo {b64} | base64 -d > "{dest}"',
            f'chmod +x "{dest}"',
            f"sed -i 's/\\r$//' \"{dest}\"",
            f'bash "{dest}" {args.action}',
        ],
        120,
        args.action,
    )


if __name__ == "__main__":
    main()
