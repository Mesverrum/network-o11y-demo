#!/usr/bin/env python3
"""Build SSM deploy JSON and optionally send to instance."""
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


def collect_paths() -> list[str]:
    paths: list[str] = []
    scripts = REPO / "local" / "scripts"
    for p in sorted(scripts.iterdir()):
        if p.suffix in {".sh", ".py"} and p.name != "ssm-sync-colocated-bundle.py":
            paths.append(str(p.relative_to(REPO)).replace("\\", "/"))
    for p in sorted((REPO / "local" / "templates" / "k8s").glob("*.tmpl")):
        paths.append(str(p.relative_to(REPO)).replace("\\", "/"))
    golden = REPO / "k8s" / "ktranslate-golden"
    if golden.is_dir():
        for p in sorted(golden.glob("*.yaml")):
            paths.append(str(p.relative_to(REPO)).replace("\\", "/"))
    return paths


def build_commands() -> list[str]:
    commands = [
        "set -euo pipefail",
        "ROOT=/opt/network-o11y-demo",
        'mkdir -p "$ROOT/local/scripts" "$ROOT/local/templates/k8s" "$ROOT/k8s/ktranslate-golden"',
    ]
    for rel in collect_paths():
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
        "systemctl restart network-o11y-fabric.service",
        "sleep 15",
        "systemctl is-active network-o11y-fabric network-o11y-telemetry k3s docker || true",
        "docker ps --format '{{.Names}}' | head -8 || true",
    ]
    return commands


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    payload = {"commands": build_commands()}
    out = REPO / "local" / ".ssm-deploy.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")

    if not args.send:
        return 0

    cmd = [
        "aws", "ssm", "send-command",
        "--instance-ids", INSTANCE,
        "--document-name", "AWS-RunShellScript",
        "--parameters", f"file://{out.as_posix()}",
        "--profile", PROFILE,
        "--region", REGION,
        "--query", "Command.CommandId",
        "--output", "text",
    ]
    cmd_id = subprocess.check_output(cmd, text=True).strip()
    print(f"command_id={cmd_id}")
    for _ in range(30):
        time.sleep(10)
        inv = subprocess.check_output(
            [
                "aws", "ssm", "get-command-invocation",
                "--command-id", cmd_id,
                "--instance-id", INSTANCE,
                "--profile", PROFILE,
                "--region", REGION,
                "--output", "json",
            ],
            text=True,
        )
        data = json.loads(inv)
        status = data.get("Status")
        print(f"status={status}")
        if status in ("Success", "Failed", "Cancelled", "TimedOut"):
            out_txt = (data.get("StandardOutputContent") or "")[:5000]
            err_txt = (data.get("StandardErrorContent") or "")[:2000]
            print(out_txt.encode("ascii", "replace").decode())
            if err_txt:
                print("STDERR:", err_txt.encode("ascii", "replace").decode())
            return 0 if status == "Success" else 1
    print("timed out waiting for SSM")
    return 1


if __name__ == "__main__":
    sys.exit(main())
