#!/usr/bin/env python3
"""Push snmp_group poller template to colocated EC2 and restart SNMP poller."""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTANCE = "i-057a78a613634b9e7"
PROFILE = "mvr"
REGION = "us-east-1"

PATHS = [
    "local/templates/poller.yaml.tmpl",
    "local/scripts/generate-groups.sh",
    "local/scripts/generate-k8s-telemetry.py",
    "local/scripts/deploy-ktranslate-golden.sh",
    "local/scripts/reload-ktranslate-devices.sh",
]


def build_commands() -> list[str]:
    commands = [
        "set -euo pipefail",
        "ROOT=/opt/network-o11y-demo",
        'mkdir -p "$ROOT/local/templates" "$ROOT/local/scripts"',
    ]
    for rel in PATHS:
        src = REPO / rel
        if not src.exists():
            raise SystemExit(f"missing {src}")
        b64 = base64.b64encode(src.read_bytes()).decode()
        dest = f"$ROOT/{rel}"
        commands.append(f"echo {b64} | base64 -d > \"{dest}\"")
        if rel.endswith(".sh"):
            commands.append(f"chmod +x \"{dest}\"")
    commands += [
        "sed -i 's/\\r$//' $ROOT/local/scripts/*.sh || true",
        "cd $ROOT/local",
        "bash scripts/generate-groups.sh",
        "grep -A2 user_tags config/poller-srl.yaml || true",
        "bash scripts/deploy-ktranslate-golden.sh",
        "export COLLECTOR_RUNTIME=k3s",
        "bash scripts/reload-ktranslate-devices.sh",
        "kubectl -n network-lab rollout status deployment/ktranslate-snmp-srl --timeout=180s",
        "POD=$(kubectl get pod -n network-lab -l app=ktranslate-snmp-srl -o jsonpath='{.items[0].metadata.name}')",
        "kubectl exec -n network-lab \"$POD\" -- grep -A2 user_tags /snmp.yaml || true",
        "echo snmp_group_deploy_complete",
    ]
    return commands


def aws(*args: str) -> str:
    r = subprocess.run(
        ["aws", "--profile", PROFILE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode:
        raise RuntimeError(r.stderr or r.stdout)
    return r.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--instance", default=INSTANCE)
    args = parser.parse_args()

    payload = {"commands": build_commands()}
    out = REPO / "local" / ".ssm-snmp-group.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")

    if not args.send:
        print("dry-run only; pass --send to apply on EC2")
        return 0

    cmd_id = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        args.instance,
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        f"file://{out.as_posix()}",
        "--region",
        REGION,
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    )
    print("command:", cmd_id)

    for i in range(36):
        time.sleep(10)
        status = aws(
            "ssm",
            "get-command-invocation",
            "--command-id",
            cmd_id,
            "--instance-id",
            args.instance,
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
        args.instance,
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
        args.instance,
        "--region",
        REGION,
        "--query",
        "StandardErrorContent",
        "--output",
        "text",
    )
    print(stdout[-4000:] if stdout else "")
    if stderr:
        print("stderr:", stderr[-2000:], file=sys.stderr)
    rc = aws(
        "ssm",
        "get-command-invocation",
        "--command-id",
        cmd_id,
        "--instance-id",
        args.instance,
        "--region",
        REGION,
        "--query",
        "ResponseCode",
        "--output",
        "text",
    )
    return 0 if status == "Success" and rc == "0" else 1


if __name__ == "__main__":
    raise SystemExit(main())
