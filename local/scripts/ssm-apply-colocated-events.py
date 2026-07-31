#!/usr/bin/env python3
"""Sync event/syslog fixes to colocated EC2 and wire SRL → ktranslate → Loki."""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
INSTANCE = "i-0a16e75d9321fa24c"
PROFILE = "mvr"
REGION = "us-east-1"

SYNC_PATHS = [
    "local/scripts/collector-runtime-ready.sh",
    "local/scripts/collector-clab-ip.sh",
    "local/scripts/syslog-config.sh",
    "local/scripts/snmp-trap-config.sh",
    "local/scripts/emit-events.sh",
    "local/scripts/events-loop.sh",
    "local/scripts/trap-gen.sh",
    "local/scripts/post-telemetry-config.sh",
    "local/scripts/stop-compose-collectors.sh",
    "local/scripts/verify-ktranslate-service-names.sh",
    "local/scripts/colocated-telemetry-bringup.sh",
    "local/scripts/deploy-ktranslate-golden.sh",
    "local/scripts/generate-k8s-telemetry.py",
    "local/scripts/host-id.sh",
    "local/scripts/write-compose-host-env.sh",
]


def build_commands() -> list[str]:
    commands = [
        "set -euo pipefail",
        "ROOT=/opt/network-o11y-demo",
        'cd "$ROOT/local"',
        "sed -i 's/\\r$//' scripts/*.sh || true",
    ]
    for rel in SYNC_PATHS:
        src = REPO / rel
        if not src.is_file():
            raise SystemExit(f"missing {src}")
        dest = f"$ROOT/{rel}"
        commands.insert(2, f'mkdir -p "$(dirname "{dest}")"')
        b64 = base64.b64encode(src.read_bytes()).decode()
        commands.insert(3, f'echo {b64} | base64 -d > "{dest}"')
        if rel.endswith(".sh"):
            commands.insert(4, f'chmod +x "{dest}"')

    # Re-build index after inserts — cleaner to build separately
    commands = ["set -euo pipefail", "ROOT=/opt/network-o11y-demo"]
    for rel in SYNC_PATHS:
        src = REPO / rel
        dest = f"$ROOT/{rel}"
        commands.append(f'mkdir -p "$(dirname "{dest}")"')
        b64 = base64.b64encode(src.read_bytes()).decode()
        commands.append(f'echo {b64} | base64 -d > "{dest}"')
        if rel.endswith(".sh"):
            commands.append(f'chmod +x "{dest}"')

    commands += [
        "sed -i 's/\\r$//' $ROOT/local/scripts/collector-runtime-ready.sh "
        "$ROOT/local/scripts/events-loop.sh $ROOT/local/scripts/trap-gen.sh "
        "$ROOT/local/scripts/syslog-config.sh $ROOT/local/scripts/snmp-trap-config.sh "
        "$ROOT/local/scripts/emit-events.sh || true",
        'cd "$ROOT/local"',
        "export COLLECTOR_RUNTIME=k3s",
        "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
        'export KTRANSLATE_CLAB_HOST="${KTRANSLATE_CLAB_HOST:-$(docker network inspect clab -f \'{{(index .IPAM.Config 0).Gateway}}\' 2>/dev/null || echo 172.20.20.1)}"',
        'echo "collector clab host=${KTRANSLATE_CLAB_HOST}"',
        "bash scripts/stop-compose-collectors.sh || true",
        "bash scripts/syslog-config.sh",
        "bash scripts/snmp-trap-config.sh",
        "ENSURE_CONFIG=0 bash scripts/emit-events.sh",
        "bash scripts/events-loop.sh stop || true",
        "bash scripts/events-loop.sh start",
        "sleep 45",
        'echo "=== CHF syslog_messages (kubectl logs if no grafana token on host) ==="',
        "kubectl -n network-lab logs deploy/ktranslate-syslog --tail=20 2>/dev/null | tail -5 || true",
        'echo "=== events-loop status ==="',
        "bash scripts/events-loop.sh status || true",
    ]
    return commands


def send_ssm(commands: list[str]) -> int:
    payload = {"commands": commands}
    out = REPO / "local" / ".ssm-apply-events.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    size = out.stat().st_size
    print(f"wrote {out} ({size} bytes)")
    if size > 97000:
        print("ERROR: SSM payload exceeds ~97KB limit", file=sys.stderr)
        return 1

    cmd = [
        "aws",
        "ssm",
        "send-command",
        "--instance-ids",
        INSTANCE,
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        f"file://{out.as_posix()}",
        "--profile",
        PROFILE,
        "--region",
        REGION,
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ]
    cmd_id = subprocess.check_output(cmd, text=True).strip()
    print(f"command_id={cmd_id}")
    for _ in range(40):
        time.sleep(10)
        inv = subprocess.check_output(
            [
                "aws",
                "ssm",
                "get-command-invocation",
                "--command-id",
                cmd_id,
                "--instance-id",
                INSTANCE,
                "--profile",
                PROFILE,
                "--region",
                REGION,
                "--output",
                "json",
            ],
            text=True,
        )
        data = json.loads(inv)
        status = data.get("Status")
        print(f"status={status}")
        if status in ("Success", "Failed", "Cancelled", "TimedOut"):
            out_txt = data.get("StandardOutputContent") or ""
            err_txt = data.get("StandardErrorContent") or ""
            print(out_txt.encode("ascii", "replace").decode()[-8000:])
            if err_txt:
                print("STDERR:", err_txt.encode("ascii", "replace").decode()[-2000:])
            return 0 if status == "Success" else 1
    print("timed out waiting for SSM", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    commands = build_commands()
    if args.dry_run:
        out = REPO / "local" / ".ssm-apply-events.json"
        out.write_text(json.dumps({"commands": commands}), encoding="utf-8")
        print(f"dry-run wrote {out} ({out.stat().st_size} bytes)")
        return 0
    return send_ssm(commands)


if __name__ == "__main__":
    sys.exit(main())
