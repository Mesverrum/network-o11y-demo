#!/usr/bin/env python3
"""Sync parallel-restore scripts to colocated EC2 and run them."""
from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import time

IID = "i-0639d827b3ecf3b82"
REPO = pathlib.Path(__file__).resolve().parents[2]
FILES = [
    "local/scripts/generate-k8s-telemetry.py",
    "local/scripts/generate-groups.sh",
    "local/scripts/deploy-ktranslate-golden.sh",
    "local/scripts/write-compose-host-env.sh",
    "local/scripts/host-id.sh",
    "local/scripts/k8s-merge-secret-literal.py",
    "local/scripts/render-alloy-otlp-export.sh",
    "local/scripts/render-alloy-netflow.sh",
    "local/scripts/render-alloy-snmp-scrape.sh",
    "local/scripts/render-alloy-snmp-trap.sh",
    "local/scripts/render-alloy-remotecfg.sh",
    "local/scripts/render-device-join.py",
    "local/scripts/alloy-snmp-discover.sh",
    "local/scripts/alloy-ktranslate-parallel-colocated.sh",
    "local/scripts/alloy-events-ports.sh",
    "local/scripts/collector-runtime-ready.sh",
    "local/scripts/softflowd.sh",
    "local/scripts/sflow-config.sh",
    "local/scripts/snmp-trap-config.sh",
    "local/scripts/syslog-config.sh",
    "local/scripts/reload-ktranslate-devices.sh",
    "local/scripts/snmp-group-utils.sh",
    "local/scripts/fabric-nodes.sh",
    "local/scripts/collector-clab-ip.sh",
    "local/scripts/collector-runtime-ready.sh",
    "local/scripts/colocated-telemetry-sanity.sh",
    "local/templates/k8s/alloy.yaml.tmpl",
    "local/templates/discovery.yaml.tmpl",
    "local/templates/poller.yaml.tmpl",
    "local/templates/compose-snippet.yaml.tmpl",
]


def send(commands: list[str], timeout: int, label: str) -> None:
    params_path = REPO / "local" / f".ssm-ktrans-parallel-{label}.json"
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
    out_path = REPO / "local" / ".ssm-last-out.txt"
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


def sync_file(rel: str) -> list[str]:
    src = REPO / rel
    b64 = base64.b64encode(src.read_bytes()).decode()
    dest = f"/opt/network-o11y-demo/{rel}"
    cmds = [
        "set -euo pipefail",
        f'mkdir -p "$(dirname "{dest}")"',
        f"echo {b64} | base64 -d > \"{dest}\"",
    ]
    if rel.endswith(".sh"):
        cmds += [f'chmod +x "{dest}"', f"sed -i 's/\\r$//' \"{dest}\""]
    else:
        cmds.append(f"sed -i 's/\\r$//' \"{dest}\" || true")
    return cmds


def main() -> None:
    for rel in FILES:
        send(sync_file(rel), 120, pathlib.Path(rel).name.replace(".", "-"))
    send(
        [
            "set -euo pipefail",
            "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
            "sed -i 's/\\r$//' /opt/network-o11y-demo/local/scripts/alloy-ktranslate-parallel-colocated.sh",
            "bash /opt/network-o11y-demo/local/scripts/alloy-ktranslate-parallel-colocated.sh",
        ],
        900,
        "parallel-restore",
    )


if __name__ == "__main__":
    main()
