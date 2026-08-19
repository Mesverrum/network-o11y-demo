#!/usr/bin/env python3
"""Deploy NetBox OSS + Diode + live Orb on colocated EC2 (self-contained; no laptop).

Uploads bring-up scripts/plugin files via SSM, then runs netbox-colocated-bringup.sh.
UI access: SSM port-forward to localhost:8000 (see printed command).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "local"
PROFILE = os.environ.get("AWS_PROFILE", "mvr")
REGION = os.environ.get("AWS_REGION", "us-east-1")
INSTANCE_TAG = "network-o11y-demo-colocated-lab"
REMOTE_ROOT = "/opt/network-o11y-demo"

BUNDLE = [
    "local/netbox-oss/Dockerfile-Plugins",
    "local/netbox-oss/plugin_requirements.txt",
    "local/netbox-oss/docker-compose.override.colocated.yml",
    "local/netbox-oss/configuration/plugins.py",
    "local/netbox-oss/docker-compose.override.yml",
    "local/scripts/netbox-colocated-bringup.sh",
    "local/scripts/orb-up.sh",
    "local/scripts/orb-down.sh",
    "local/scripts/orb-render-config.py",
    "local/orb/compose.yaml",
    "local/orb/out/.gitkeep",
]


def aws_cli() -> list[str]:
    for candidate in ("aws", "aws.exe"):
        if shutil.which(candidate):
            return [candidate]
    raise RuntimeError("aws CLI not found")


def aws(*args: str) -> str:
    cmd = aws_cli() + ["--profile", PROFILE, "--region", REGION, *args]
    env = os.environ.copy()
    env.setdefault("AWS_PAGER", "")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Avoid aws.exe crashing on emoji in SSM stdout under cp1252 consoles.
    env["AWS_CLI_FILE_ENCODING"] = "UTF-8"
    proc = subprocess.run(
        cmd,
        capture_output=True,
        env=env,
        check=False,
    )
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError(err.strip() or out.strip() or f"aws exit {proc.returncode}")
    return out


def instance_id() -> str:
    out = aws(
        "ec2",
        "describe-instances",
        "--filters",
        f"Name=tag:Name,Values={INSTANCE_TAG}",
        "Name=instance-state-name,Values=running",
        "--query",
        "Reservations[0].Instances[0].InstanceId",
        "--output",
        "text",
    ).strip()
    if not out or out == "None":
        raise RuntimeError("No running colocated instance — make colocated-lab-up first")
    return out


def b64_lines(rel: str) -> list[str]:
    src = ROOT / rel.replace("/", os.sep)
    if not src.is_file():
        raise FileNotFoundError(src)
    data = base64.b64encode(src.read_bytes()).decode("ascii")
    dest = f"{REMOTE_ROOT}/{rel}"
    parent = str(Path(dest).parent).replace("\\", "/")
    lines = [f'mkdir -p "{parent}"', f'echo {data} | base64 -d > "{dest}"']
    if rel.endswith(".sh"):
        lines.append(f'chmod +x "{dest}"')
        lines.append(f"sed -i 's/\\r$//' \"{dest}\"")
    if rel.endswith(".py"):
        lines.append(f"sed -i 's/\\r$//' \"{dest}\" || true")
    return lines


def remote_script() -> str:
    lines = [
        "set -euo pipefail",
        f"ROOT={REMOTE_ROOT}",
        'echo "==> syncing NetBox/Orb/Diode bundle"',
    ]
    for rel in BUNDLE:
        lines.extend(b64_lines(rel))
    lines += [
        "mkdir -p $ROOT/local/orb/out $ROOT/local/netbox-oss/configuration",
        "sed -i 's/\\r$//' $ROOT/local/scripts/*.sh $ROOT/local/scripts/*.py || true",
        'echo "==> running netbox-colocated-bringup.sh (NetBox build + Diode + Orb live)"',
        "bash $ROOT/local/scripts/netbox-colocated-bringup.sh",
    ]
    return "\n".join(lines) + "\n"


def wait_invocation(cid: str, iid: str, timeout_s: int = 3600) -> int:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(20)
        raw = aws(
            "ssm",
            "get-command-invocation",
            "--command-id",
            cid,
            "--instance-id",
            iid,
            "--output",
            "json",
        )
        data = json.loads(raw)
        status = data.get("Status")
        print(f"SSM status={status}")
        if status in ("Success", "Failed", "Cancelled", "TimedOut"):
            out = (data.get("StandardOutputContent") or "")[-12000:]
            err = (data.get("StandardErrorContent") or "")[-4000:]
            sys.stdout.buffer.write(out.encode("utf-8", "replace") + b"\n")
            if err:
                sys.stderr.buffer.write(b"STDERR: " + err.encode("utf-8", "replace") + b"\n")
            if status == "Success":
                print()
                print("Access NetBox UI from your laptop:")
                print(
                    f"  aws ssm start-session --target {iid} --profile {PROFILE} --region {REGION} "
                    f"--document-name AWS-StartPortForwardingSession "
                    f"--parameters portNumber=8000,localPortNumber=8000"
                )
                print("  then open http://127.0.0.1:8000/  (admin / admin)")
                print("Grafana: Infinity datasource netbox-api on dashboards 20/22/24/25; Orb metrics collector=~\"orb\"")
            return 0 if status == "Success" else 1
    print("timed out waiting for SSM", file=sys.stderr)
    return 1


def main() -> int:
    try:
        iid = instance_id()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    # Ensure out gitkeep exists for bundle
    keep = LOCAL / "orb" / "out" / ".gitkeep"
    keep.parent.mkdir(parents=True, exist_ok=True)
    if not keep.exists():
        keep.write_text("", encoding="utf-8")

    script = remote_script()
    param_file = LOCAL / ".ssm-netbox-colocated.json"
    param_file.write_text(json.dumps({"commands": [script]}), encoding="utf-8", newline="\n")

    print(f"Instance: {iid}")
    print("Deploying NetBox + Diode + live Orb on colocated EC2 (long: image build)...")
    cid = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        iid,
        "--document-name",
        "AWS-RunShellScript",
        "--timeout-seconds",
        "3600",
        "--parameters",
        f"file://{param_file.as_posix()}",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ).strip()
    print(f"CommandId: {cid}")
    return wait_invocation(cid, iid)


if __name__ == "__main__":
    raise SystemExit(main())
