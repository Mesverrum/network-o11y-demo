#!/usr/bin/env python3
"""Deploy hybrid-probe to AWS dashboard-lab instances via SSM."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "terraform" / "aws-dashboard-lab"
PROBE = ROOT / "local" / "hybrid-probe"
ENV = ROOT / "local" / ".env"
PROFILE = "mvr"
REGION = "us-east-1"


def aws(*args: str) -> str:
    win = Path("/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe")
    cmd = ["aws"] if subprocess.run(["which", "aws"], capture_output=True).returncode == 0 else [str(win)]
    cmd += ["--profile", PROFILE, "--region", REGION, *args]
    return subprocess.check_output(cmd, text=True)


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    tf = ROOT / "local" / "scripts" / "aws-lab-terraform.sh"
    ids_json = subprocess.check_output(["bash", str(tf), str(LAB), "output", "-json", "traffic_instance_ids"], text=True)
    ids = json.loads(ids_json)
    if not ids:
        print("No instances — run make -C local aws-lab-up", file=sys.stderr)
        return 1

    managed = json.loads(
        aws(
            "ssm",
            "describe-instance-information",
            "--output",
            "json",
        )
    ).get("InstanceInformationList", [])
    managed_ids = {x["InstanceId"] for x in managed}
    missing = [i for i in ids if i not in managed_ids]
    if missing:
        print(
            "SSM agent not registered for: " + ", ".join(missing),
            file=sys.stderr,
        )
        print(
            "Re-apply lab to bake probe via userdata: make -C local aws-lab-up",
            file=sys.stderr,
        )
        return 1

    env = load_env()
    for k in ("GC_OTLP_URL", "GC_OTLP_ACCOUNT", "GC_OTLP_KEY"):
        if not env.get(k):
            print(f"Missing {k} in local/.env", file=sys.stderr)
            return 1

    script = f"""#!/bin/bash
set -euo pipefail
mkdir -p /opt/hybrid-probe
cat >/opt/hybrid-probe/.env <<'EOF'
GC_OTLP_URL={env['GC_OTLP_URL']}
GC_OTLP_ACCOUNT={env['GC_OTLP_ACCOUNT']}
GC_OTLP_KEY={env['GC_OTLP_KEY']}
EOF
"""
    for name in ("agent.py", "otel_push.py", "targets-aws.yaml"):
        data = base64.b64encode((PROBE / name).read_bytes()).decode()
        script += f"echo '{data}' | base64 -d >/opt/hybrid-probe/{name}\n"

    script += """
dnf install -y python3 python3-pip >/dev/null
pip3 install -q pyyaml --ignore-scripts
cat >/etc/systemd/system/hybrid-probe.service <<'UNIT'
[Unit]
Description=Hybrid mesh probe agent
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/hybrid-probe
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /opt/hybrid-probe/agent.py --config /opt/hybrid-probe/targets-aws.yaml --listen 18080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now hybrid-probe.service
systemctl is-active hybrid-probe.service
"""

    params = json.dumps({"commands": [script]})
    send_args = ["ssm", "send-command", "--document-name", "AWS-RunShellScript"]
    for iid in ids:
        send_args.extend(["--instance-ids", iid])
    send_args += ["--parameters", params, "--query", "Command.CommandId", "--output", "text"]
    cid = aws(*send_args).strip()
    print(f"CommandId: {cid}")
    time.sleep(20)
    for iid in ids:
        out = aws("ssm", "get-command-invocation", "--command-id", cid, "--instance-id", iid, "--output", "json")
        j = json.loads(out)
        print(f"\n=== {iid} {j.get('Status')} ===")
        print(j.get("StandardOutputContent", "")[-2000:])
        if j.get("StandardErrorContent"):
            print("stderr:", j.get("StandardErrorContent")[-1000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
