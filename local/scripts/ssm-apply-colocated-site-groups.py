#!/usr/bin/env python3
"""Deploy colocated site-scoped SNMP groups to EC2 and rediscover."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTANCE = "i-057a78a613634b9e7"
PROFILE = "mvr"
REGION = "us-east-1"

PATHS = [
    "local/groups/srl-hq.env.sample",
    "local/groups/srl-branch1.env.sample",
    "local/groups/srl-branch2.env.sample",
    "local/scripts/colocated-snmp-groups.sh",
    "local/scripts/snmp-group-utils.sh",
    "local/scripts/update-snmp-targets.sh",
    "local/scripts/snmp-trap-config.sh",
    "local/scripts/colocated-telemetry-bringup.sh",
    "local/scripts/colocated-telemetry-sanity.sh",
    "local/scripts/reload-ktranslate-devices.sh",
    "local/scripts/deploy-ktranslate-golden.sh",
    "local/scripts/verify-ktranslate-service-names.sh",
    "local/scripts/generate-k8s-telemetry.py",
    "local/templates/poller.yaml.tmpl",
    "local/scripts/generate-groups.sh",
]


def build_commands() -> list[str]:
    commands = [
        "set -euo pipefail",
        "ROOT=/opt/network-o11y-demo",
        'mkdir -p "$ROOT/local/groups" "$ROOT/local/scripts" "$ROOT/local/templates"',
    ]
    for rel in PATHS:
        src = REPO / rel
        b64 = base64.b64encode(src.read_bytes()).decode()
        dest = f"$ROOT/{rel}"
        commands.append(f"echo {b64} | base64 -d > \"{dest}\"")
        if rel.endswith(".sh"):
            commands.append(f"chmod +x \"{dest}\"")
    commands += [
        "sed -i 's/\\r$//' $ROOT/local/scripts/*.sh $ROOT/local/groups/*.env $ROOT/local/groups/*.env.sample 2>/dev/null || true",
        "cd $ROOT/local",
        "export LAB_FABRIC_PROFILE=colocated",
        "export COLLECTOR_RUNTIME=k3s",
        "bash scripts/colocated-snmp-groups.sh",
        "rm -f state/devices-srl.yaml state/devices-srl.yaml.prev 2>/dev/null || true",
        "kubectl -n network-lab delete deployment ktranslate-snmp-srl --ignore-not-found=true",
        "bash scripts/enable-snmp-srl.sh",
        "bash scripts/update-snmp-targets.sh",
        "COLLECTOR_RUNTIME=k3s bash scripts/run-discovery-all.sh",
        "bash scripts/deploy-ktranslate-golden.sh",
        "bash scripts/snmp-trap-config.sh || true",
        "bash scripts/colocated-telemetry-sanity.sh || true",
        "yq 'length' state/devices-srl-hq.yaml state/devices-srl-branch1.yaml state/devices-srl-branch2.yaml 2>/dev/null || true",
        "echo colocated_site_groups_complete",
    ]
    return commands


def aws(*args: str) -> str:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        ["aws", "--profile", PROFILE, *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if r.returncode:
        raise RuntimeError(r.stderr or r.stdout)
    return r.stdout.strip()


def main() -> int:
    payload = {"commands": build_commands()}
    out = REPO / "local" / ".ssm-colocated-site-groups.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {out}")

    cmd_id = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        INSTANCE,
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        f"file://{out.as_posix()}",
        "--region",
        REGION,
        "--timeout-seconds",
        "900",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    )
    print("command:", cmd_id)
    status = "InProgress"
    for i in range(60):
        time.sleep(15)
        status = aws(
            "ssm",
            "get-command-invocation",
            "--command-id",
            cmd_id,
            "--instance-id",
            INSTANCE,
            "--region",
            REGION,
            "--query",
            "Status",
            "--output",
            "text",
        )
        print(f"poll {i + 1}: {status}")
        if status in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
    stdout = aws(
        "ssm",
        "get-command-invocation",
        "--command-id",
        cmd_id,
        "--instance-id",
        INSTANCE,
        "--region",
        REGION,
        "--query",
        "StandardOutputContent",
        "--output",
        "text",
    )
    stderr = aws(
        "ssm",
        "get-command-invocation",
        "--command-id",
        cmd_id,
        "--instance-id",
        INSTANCE,
        "--region",
        REGION,
        "--query",
        "StandardErrorContent",
        "--output",
        "text",
    )
    print(stdout[-5000:] if stdout else "")
    if stderr:
        print("stderr:", stderr[-3000:], file=sys.stderr)
    return 0 if status == "Success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
