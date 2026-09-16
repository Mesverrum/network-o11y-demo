#!/usr/bin/env python3
"""Reload campus ktranslate (us-east-2) with the workshop static device list.

Pushes local/workshop/campus-snmp.yaml to network-o11y-campus-lab and recreates
campus-workshop-ktrans-snmp on 172.20.20.9 → Alloy 172.20.20.8 → marcnetterfield1.

Does not redeploy the campus-core fabric. Discovery-on-start is off (host mounts
cannot chtimes the snmp.yaml file).
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
from pathlib import Path

PROFILE, REGION, IID = "mvr", "us-east-2", "i-08eaccaf566dda685"
YAML = Path(__file__).resolve().parents[1] / "workshop" / "campus-snmp.yaml"


def send(commands: list[str], timeout: int = 90) -> str:
    p = Path(__file__).resolve().parents[1] / "state" / "ssm-campus-workshop-up.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    proc = subprocess.run(
        [
            "aws", "--profile", PROFILE, "--region", REGION, "ssm", "send-command",
            "--instance-ids", IID, "--document-name", "AWS-RunShellScript",
            "--comment", "campus-workshop-ktrans-up", "--timeout-seconds", str(timeout),
            "--parameters", f"file://{p}", "--query", "Command.CommandId", "--output", "text",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    p.unlink(missing_ok=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-600:])
    return proc.stdout.strip()


def main() -> int:
    b64 = base64.b64encode(YAML.read_bytes()).decode("ascii")
    cid = send(
        [
            "install -d /opt/network-o11y-campus/telemetry/state",
            f"echo {b64} | base64 -d > /opt/network-o11y-campus/telemetry/state/snmp.yaml",
            "docker rm -f campus-workshop-ktrans-snmp",
            "docker run -d --name campus-workshop-ktrans-snmp --restart unless-stopped --network fixedips --ip 172.20.20.9 -e OTEL_SERVICE_NAME=ktranslate-snmp-workshop -v /opt/network-o11y-campus/telemetry/state/snmp.yaml:/snmp.yaml:ro kentik/ktranslate:latest --format=otel --otel.protocol=grpc --otel.endpoint=http://172.20.20.8:4317 --snmp=/snmp.yaml --metalisten=0.0.0.0:9997 --sinks=otel --metrics=jchf --tee_logs=true --service_name=ktranslate-snmp-workshop --max_flows_per_message=100",
            "sleep 8",
            "docker logs campus-workshop-ktrans-snmp 2>&1 | tr -cd '\\11\\12\\15\\40-\\176\\n' | grep -E 'Setting up|Error|devices|profile' | tail -30",
        ]
    )
    print("cmd", cid)
    for _ in range(24):
        time.sleep(5)
        st = subprocess.run(
            [
                "aws", "--profile", PROFILE, "--region", REGION, "ssm",
                "get-command-invocation", "--command-id", cid, "--instance-id", IID,
                "--query", "Status", "--output", "text",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.strip()
        print(st)
        if st in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
    proc = subprocess.run(
        [
            "aws", "ssm", "get-command-invocation", "--profile", PROFILE, "--region", REGION,
            "--command-id", cid, "--instance-id", IID, "--output", "json",
        ],
        capture_output=True,
    )
    d = json.loads(proc.stdout.decode("utf-8", "replace"))
    print((d.get("StandardOutputContent") or "")[-2000:])
    return 0 if d.get("Status") == "Success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
