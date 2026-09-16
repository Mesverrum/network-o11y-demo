#!/usr/bin/env python3
"""Sync glue harness to colocated, upload the exporter binary, run Alloy cutover."""
from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import time
import uuid

IID = "i-0639d827b3ecf3b82"
REPO = pathlib.Path(__file__).resolve().parents[2]
BUCKET = "mvr-net-o11y-xfer-494614287886"
REGION = "us-east-1"
BIN = REPO / "local" / "topology-exporter" / "topology-exporter-linux-amd64"
FILES = [
    "local/scripts/render-alloy-snmp-scrape.sh",
    "local/scripts/render-snmp-topology-overrides.sh",
    "local/scripts/generate-k8s-telemetry.py",
    "local/scripts/generate-groups.sh",
    "local/scripts/write-compose-host-env.sh",
    "local/scripts/host-id.sh",
    "local/scripts/alloy-topology-glue-colocated.sh",
    "local/scripts/apply-discovered-mibs.sh",
    "local/scripts/apply-discovered-mibs.py",
    "local/scripts/fabric-nodes.sh",
    "local/topology-exporter/config-alloy-glue.yaml",
    "local/topology-exporter/aliases-colocated.yml",
    "local/templates/k8s/alloy.yaml.tmpl",
    "local/alloy/config.alloy",
]


def send(commands: list[str], timeout: int, label: str) -> None:
    params_path = REPO / "local" / f".ssm-topo-glue-{label}.json"
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
            REGION,
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
    out_path = REPO / "local" / ".ssm-topo-glue-out.txt"
    for _ in range(timeout // 3 + 15):
        raw = subprocess.check_output(
            [
                "aws",
                "ssm",
                "get-command-invocation",
                "--profile",
                "mvr",
                "--region",
                REGION,
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
            print(stdout[-8000:] if stdout else "(no stdout)")
            if stderr:
                print("STDERR:", stderr[-3000:])
            if status != "Success":
                raise SystemExit(1)
            return
        time.sleep(3)
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


def ensure_bucket() -> None:
    r = subprocess.run(
        ["aws", "s3api", "head-bucket", "--bucket", BUCKET, "--profile", "mvr"],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        return
    print(f"creating s3://{BUCKET}", flush=True)
    subprocess.check_call(
        ["aws", "s3api", "create-bucket", "--bucket", BUCKET, "--profile", "mvr", "--region", REGION],
    )
    subprocess.check_call(
        [
            "aws",
            "s3api",
            "put-public-access-block",
            "--bucket",
            BUCKET,
            "--profile",
            "mvr",
            "--public-access-block-configuration",
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
        ]
    )


def upload_binary() -> str:
    if not BIN.is_file():
        raise SystemExit(f"missing {BIN} — build the linux amd64 binary first")
    key = f"topology-exporter/{uuid.uuid4().hex}/topology-exporter-linux-amd64"
    print(f"uploading {BIN} -> s3://{BUCKET}/{key}", flush=True)
    subprocess.check_call(
        ["aws", "s3", "cp", str(BIN), f"s3://{BUCKET}/{key}", "--profile", "mvr", "--region", REGION],
    )
    url = subprocess.check_output(
        [
            "aws",
            "s3",
            "presign",
            f"s3://{BUCKET}/{key}",
            "--expires-in",
            "3600",
            "--profile",
            "mvr",
            "--region",
            REGION,
        ],
        text=True,
    ).strip()
    return url


def main() -> None:
    ensure_bucket()
    url = upload_binary()
    dest = "/opt/network-o11y-demo/local/topology-exporter/topology-exporter-linux-amd64"
    send(
        [
            "set -euo pipefail",
            f'mkdir -p "$(dirname "{dest}")"',
            f'curl -fsSL -o "{dest}" "{url}"',
            f'chmod +x "{dest}"',
            f'ls -lh "{dest}"',
        ],
        180,
        "binary",
    )
    for rel in FILES:
        send(sync_file(rel), 120, pathlib.Path(rel).name.replace(".", "-")[:40])
    send(
        [
            "set -euo pipefail",
            "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
            "export COLLECTOR_RUNTIME=k3s",
            "sed -i 's/\\r$//' /opt/network-o11y-demo/local/scripts/alloy-topology-glue-colocated.sh",
            "bash /opt/network-o11y-demo/local/scripts/alloy-topology-glue-colocated.sh",
        ],
        600,
        "glue-apply",
    )


if __name__ == "__main__":
    main()
