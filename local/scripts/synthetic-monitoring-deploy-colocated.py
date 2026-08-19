#!/usr/bin/env python3
"""Deploy Grafana SM private-probe agent to colocated EC2 k3s via SSM."""
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
STATE = ROOT / "local" / "state"
MANIFEST = STATE / "sm-agent-colocated.yaml"
PROFILE = "mvr"
REGION = "us-east-1"
INSTANCE_TAG = "network-o11y-demo-colocated-lab"
DEFAULT_API_SERVER = "synthetic-monitoring-grpc-us-east-0.grafana.net:443"
GCX_CONTEXT = os.environ.get("GCX_CONTEXT", "marcnetterfield1")

# Import shared creds helper
import importlib.util

_spec = importlib.util.spec_from_file_location("sm_creds", Path(__file__).parent / "sm_creds.py")
_sm = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(_sm)


def aws_cli() -> list[str]:
    for candidate in ("aws", "aws.exe"):
        if shutil.which(candidate):
            return [candidate]
    raise RuntimeError("aws CLI not found")


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
        raise RuntimeError("No running colocated instance")
    return out


def ensure_manifest() -> None:
    creds = _sm.probe_creds("colocated")
    token = os.environ.get("SM_PROBE_COLOCATED_TOKEN", "").strip() or creds["api_token"]
    api_url = creds.get("api_server", DEFAULT_API_SERVER)
    STATE.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gcx",
            "--context",
            GCX_CONTEXT,
            "synthetic-monitoring",
            "probes",
            "deploy",
            "--probe-name",
            "sm-agent-colocated",
            "--token",
            token,
            "--api-server-url",
            api_url,
        ],
        check=True,
        stdout=MANIFEST.open("w", encoding="utf-8", newline="\n"),
    )
    # gcx deploy only sets API_* env vars; current agent images require CLI flags.
    # Do not YAML-roundtrip the Secret (corrupts base64). String-patch only.
    text = MANIFEST.read_text(encoding="utf-8")
    if "hostNetwork" not in text:
        text = text.replace(
            "      containers:\n",
            "      hostNetwork: true\n      dnsPolicy: ClusterFirstWithHostNet\n      containers:\n",
            1,
        )
    if "--api-token=$(API_ACCESS_TOKEN)" not in text:
        needle = "          image: grafana/synthetic-monitoring-agent:latest\n"
        if needle not in text:
            # tolerate pinned tags
            import re

            m = re.search(r"          image: grafana/synthetic-monitoring-agent:\S+\n", text)
            if not m:
                raise RuntimeError("deploy manifest missing sm-agent image line")
            needle = m.group(0)
        text = text.replace(
            needle,
            needle
            + "          args:\n"
            + "            - --api-server-address=$(API_SERVER_URL)\n"
            + "            - --api-token=$(API_ACCESS_TOKEN)\n",
            1,
        )
    MANIFEST.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    try:
        ensure_manifest()
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(str(e), file=sys.stderr)
        return 1
    if not MANIFEST.is_file():
        print(f"Failed to write {MANIFEST}", file=sys.stderr)
        return 1

    data = base64.b64encode(MANIFEST.read_bytes()).decode()
    script = f"""#!/bin/bash
set -euo pipefail
echo '{data}' | base64 -d >/tmp/sm-agent-colocated.yaml
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl create namespace synthetic-monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl -n synthetic-monitoring delete deploy sm-agent-colocated-sm-agent --ignore-not-found
kubectl -n synthetic-monitoring delete secret sm-agent-colocated-sm-agent --ignore-not-found
kubectl apply -f /tmp/sm-agent-colocated.yaml
kubectl -n synthetic-monitoring rollout status deployment/sm-agent-colocated-sm-agent --timeout=180s
kubectl -n synthetic-monitoring get pods -o wide
kubectl -n synthetic-monitoring logs deploy/sm-agent-colocated-sm-agent --tail=20 || true
"""

    iid = instance_id()
    params = json.dumps({"commands": [script]})
    cid = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        iid,
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        params,
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ).strip()
    print(f"Instance: {iid}")
    print(f"CommandId: {cid}")
    time.sleep(45)
    out = aws(
        "ssm",
        "get-command-invocation",
        "--command-id",
        cid,
        "--instance-id",
        iid,
        "--query",
        "[Status,StandardOutputContent]",
        "--output",
        "text",
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
