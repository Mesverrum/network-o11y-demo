#!/usr/bin/env python3
"""Minimal SSM bundle — only colocated-specific files not on GitHub main."""
from __future__ import annotations

import base64
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

PATHS = [
    "local/scripts/colocated-fabric-bringup.sh",
    "local/scripts/colocated-telemetry-bringup.sh",
    "local/scripts/deploy-ktranslate-golden.sh",
    "local/scripts/stop-compose-collectors.sh",
    "local/scripts/verify-ktranslate-service-names.sh",
    "local/scripts/collector-runtime-ready.sh",
    "local/scripts/syslog-config.sh",
    "local/scripts/snmp-trap-config.sh",
    "local/scripts/emit-events.sh",
    "local/scripts/events-loop.sh",
    "local/scripts/trap-gen.sh",
    "local/scripts/collector-clab-ip.sh",
    "local/scripts/generate-k8s-telemetry.py",
    "local/scripts/write-compose-host-env.sh",
    "local/scripts/host-id.sh",
    "local/scripts/generate-groups.sh",
    "local/scripts/run-discovery.sh",
    "local/templates/k8s/namespace.yaml.tmpl",
    "local/templates/k8s/alloy.yaml.tmpl",
    "local/templates/k8s/gnmic.yaml.tmpl",
]

def main() -> None:
    for p in sorted((REPO / "k8s/ktranslate-golden").glob("*.yaml")):
        PATHS.append(str(p.relative_to(REPO)).replace("\\", "/"))

    commands = [
        "set -euo pipefail",
        "ROOT=/opt/network-o11y-demo",
        'mkdir -p "$ROOT/local/scripts" "$ROOT/local/templates/k8s" "$ROOT/k8s/ktranslate-golden"',
    ]
    for rel in PATHS:
        src = REPO / rel
        b64 = base64.b64encode(src.read_bytes()).decode()
        dest = f"$ROOT/{rel}"
        commands.append(f"echo {b64} | base64 -d > \"{dest}\"")
        if rel.endswith(".sh"):
            commands.append(f"chmod +x \"{dest}\"")
    commands += [
        "sed -i 's/\\r$//' $ROOT/local/scripts/colocated-*.sh $ROOT/local/scripts/deploy-ktranslate-golden.sh $ROOT/local/scripts/stop-compose-collectors.sh $ROOT/local/scripts/verify-ktranslate-service-names.sh $ROOT/local/scripts/collector-clab-ip.sh $ROOT/local/scripts/write-compose-host-env.sh $ROOT/local/scripts/host-id.sh || true",
        "nohup bash -lc 'systemctl reset-failed network-o11y-fabric; systemctl start network-o11y-fabric' >/tmp/fabric-nohup.log 2>&1 &",
        "echo started_fabric_background",
    ]
    out = REPO / "local" / ".ssm-deploy-min.json"
    out.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    print(out, out.stat().st_size)

if __name__ == "__main__":
    main()
