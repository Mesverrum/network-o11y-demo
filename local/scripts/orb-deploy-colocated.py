#!/usr/bin/env python3
"""Deploy Orb agent sidecar to colocated EC2 (dry-run SNMP → /opt/.../local/orb/out/).

Uploads local/orb + orb scripts via SSM, then runs orb-up on the host.
Does not run Orb on the laptop — use this when local resources are constrained.
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

# Files to sync (relative to repo root)
BUNDLE = [
    "local/orb/compose.yaml",
    "local/orb/README.md",
    "local/orb/out/.gitkeep",
    "local/scripts/orb-up.sh",
    "local/scripts/orb-down.sh",
    "local/scripts/orb-render-config.py",
    "local/scripts/softflowd.sh",
    "local/scripts/sflow-config.sh",
]


def aws_cli() -> list[str]:
    for candidate in ("aws", "aws.exe"):
        if shutil.which(candidate):
            return [candidate]
    raise RuntimeError("aws CLI not found (use Windows aws --profile mvr)")


def aws(*args: str) -> str:
    cmd = aws_cli() + ["--profile", PROFILE, "--region", REGION, *args]
    return subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")


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
        raise RuntimeError(
            "No running colocated instance — make -C local colocated-lab-up first"
        )
    return out


def b64_write(rel: str) -> list[str]:
    src = ROOT / rel.replace("/", os.sep)
    if not src.is_file():
        raise FileNotFoundError(src)
    data = base64.b64encode(src.read_bytes()).decode("ascii")
    dest = f"{REMOTE_ROOT}/{rel}"
    parent = str(Path(dest).parent).replace("\\", "/")
    lines = [
        f'mkdir -p "{parent}"',
        f"echo {data} | base64 -d > \"{dest}\"",
    ]
    if rel.endswith(".sh"):
        lines.append(f'chmod +x "{dest}"')
    return lines


def remote_script() -> str:
    # Env for orb-up on EC2 (fabric SNMP on clab bridge)
    # Default pktvisor ON for colocated redeploys unless explicitly disabled.
    env_exports = {
        "ORB_DRY_RUN": os.environ.get("ORB_DRY_RUN", "0"),
        "ORB_SNMP_TARGETS": os.environ.get("ORB_SNMP_TARGETS", "172.20.20.0/24"),
        "ORB_SNMP_COMMUNITY": os.environ.get("ORB_SNMP_COMMUNITY", "public"),
        "ORB_PKTVISOR": os.environ.get("ORB_PKTVISOR", "1"),
        "ORB_OTLP": os.environ.get("ORB_OTLP", "1"),
        "ORB_SNMP_SCHEDULE": os.environ.get("ORB_SNMP_SCHEDULE", "*/2 * * * *"),
        "ORB_AGENT_NAME": os.environ.get("ORB_AGENT_NAME", "network-o11y-colocated"),
        "ORB_DIODE_TARGET": os.environ.get("ORB_DIODE_TARGET", "grpc://127.0.0.1:8080/diode"),
        "ORB_PKTVISOR_NETFLOW_PORT": os.environ.get("ORB_PKTVISOR_NETFLOW_PORT", "19995"),
        "ORB_PKTVISOR_SFLOW_PORT": os.environ.get("ORB_PKTVISOR_SFLOW_PORT", "16343"),
        "DIODE_CLIENT_ID": os.environ.get("DIODE_CLIENT_ID", ""),
        "DIODE_CLIENT_SECRET": os.environ.get("DIODE_CLIENT_SECRET", ""),
    }
    lines = [
        "set -euo pipefail",
        f"ROOT={REMOTE_ROOT}",
        "LAB=$ROOT/local",
        # Prefer creds already written on the host by netbox-colocated-bringup
        "if [[ -f $LAB/.env ]]; then set -a; source <(sed 's/\\r$//' $LAB/.env | grep -E '^(ORB_|DIODE_|NETBOX_)' || true); set +a; fi",
        'echo "==> syncing Orb bundle"',
    ]
    for rel in BUNDLE:
        lines.extend(b64_write(rel))
    lines += [
        "sed -i 's/\\r$//' $LAB/scripts/orb-*.sh $LAB/scripts/softflowd.sh $LAB/scripts/sflow-config.sh || true",
        "chmod +x $LAB/scripts/softflowd.sh $LAB/scripts/sflow-config.sh || true",
        "mkdir -p $LAB/orb/out",
    ]
    for k, v in env_exports.items():
        # shell-safe single-quoted values
        safe = v.replace("'", "'\"'\"'")
        lines.append(f"export {k}='{safe}'")
    lines += [
        # Persist pktvisor flags into remote .env for future orb-up / softflowd
        "python3 - <<'PY'",
        "import pathlib, re",
        "p = pathlib.Path('/opt/network-o11y-demo/local/.env')",
        "text = p.read_text(encoding='utf-8') if p.exists() else ''",
        "pairs = {",
        "  'ORB_PKTVISOR': '1',",
        "  'ORB_OTLP': '1',",
        "  'ORB_PKTVISOR_NETFLOW_PORT': '19995',",
        "  'ORB_PKTVISOR_SFLOW_PORT': '16343',",
        "}",
        "for k, v in pairs.items():",
        "    line = f'{k}={v}'",
        "    if re.search(rf'^{k}=.*$', text, flags=re.M):",
        "        text = re.sub(rf'^{k}=.*$', line, text, count=1, flags=re.M)",
        "    else:",
        "        if text and not text.endswith('\\n'):",
        "            text += '\\n'",
        "        text += line + '\\n'",
        "p.write_text(text, encoding='utf-8')",
        "print('updated', p, 'pktvisor flags')",
        "PY",
        'echo "==> stopping any prior orb-agent"',
        "bash $LAB/scripts/orb-down.sh || true",
        'echo "==> orb-up on colocated host (pktvisor+diode+otlp)"',
        "bash $LAB/scripts/orb-up.sh",
        'echo "==> dual softflowd (ktranslate:9995 + pktvisor:19995)"',
        "bash $LAB/scripts/softflowd.sh || echo 'WARN softflowd failed'",
        'echo "==> dual sFlow (ktranslate:6343 + pktvisor:16343)"',
        "bash $LAB/scripts/sflow-config.sh || echo 'WARN sflow failed'",
        'echo "==> light traffic for flow export"',
        "bash $LAB/scripts/traffic.sh || true",
        'echo "==> status"',
        "docker ps --filter name=orb-agent --format 'table {{.Names}}\\t{{.Status}}'",
        "ss -ulnp | grep -E '19995|16343|10853' || netstat -ulnp 2>/dev/null | grep -E '19995|16343|10853' || true",
        "docker exec client1 pgrep -a softflowd || true",
        "docker logs orb-agent --tail 40 || true",
    ]
    return "\n".join(lines) + "\n"


def wait_invocation(cid: str, iid: str, timeout_s: int = 600) -> int:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(15)
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
            out = (data.get("StandardOutputContent") or "")[-8000:]
            err = (data.get("StandardErrorContent") or "")[-3000:]
            if out:
                print(out)
            if err:
                print("STDERR:", err, file=sys.stderr)
            return 0 if status == "Success" else 1
    print("timed out waiting for SSM", file=sys.stderr)
    return 1


def remote_down_script() -> str:
    return "\n".join(
        [
            "set -euo pipefail",
            f"LAB={REMOTE_ROOT}/local",
            "if [[ -x $LAB/scripts/orb-down.sh ]]; then bash $LAB/scripts/orb-down.sh; else docker rm -f orb-agent || true; fi",
            "docker ps -a --filter name=orb-agent --format '{{.Names}} {{.Status}}' || true",
        ]
    ) + "\n"


def send(iid: str, script: str, label: str) -> int:
    params = json.dumps({"commands": [script]})
    param_file = LOCAL / ".ssm-orb-deploy.json"
    param_file.write_text(params, encoding="utf-8", newline="\n")
    print(f"Instance: {iid}")
    print(label)
    cid = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        iid,
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        f"file://{param_file.as_posix()}",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ).strip()
    print(f"CommandId: {cid}")
    return wait_invocation(cid, iid)


def main() -> int:
    down = "--down" in sys.argv
    try:
        iid = instance_id()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    if down:
        return send(iid, remote_down_script(), "Stopping Orb on colocated host")
    return send(
        iid,
        remote_script(),
        f"Uploading Orb -> {REMOTE_ROOT}/local/orb (dry_run)",
    )


if __name__ == "__main__":
    raise SystemExit(main())
