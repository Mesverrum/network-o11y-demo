#!/usr/bin/env python3
"""SSM: push dual-OTLP Alloy bits to colocated lab and redeploy Alloy."""
from __future__ import annotations

import base64
import json
import pathlib
import re
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
INSTANCE = "i-0639d827b3ecf3b82"
PROFILE = "mvr"
REGION = "us-east-1"

# Files required for dual OTLP on the host (relative to repo root).
SYNC_RELS = [
    "local/alloy/config.alloy",
    "local/compose-base.yaml",
    "local/scripts/render-alloy-otlp-export.sh",
    "local/scripts/write-compose-host-env.sh",
    "local/scripts/generate-k8s-telemetry.py",
    "local/scripts/deploy-ktranslate-golden.sh",
    "local/templates/k8s/alloy.yaml.tmpl",
]


def load_env(path: pathlib.Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def aws(*args: str) -> str:
    return subprocess.check_output(["aws", *args], text=True).strip()


def b64_file(rel: str) -> str:
    src = REPO / rel
    if not src.exists():
        raise SystemExit(f"missing {src}")
    return base64.b64encode(src.read_bytes()).decode()


def shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def build_commands() -> list[str]:
    env = load_env(REPO / "local" / ".env")
    for k in ("GC_OTLP_URL_2", "GC_OTLP_ACCOUNT_2", "GC_OTLP_KEY_2"):
        if not env.get(k):
            raise SystemExit(f"missing {k} in local/.env")
    extra3 = all(env.get(k) for k in ("GC_OTLP_URL_3", "GC_OTLP_ACCOUNT_3", "GC_OTLP_KEY_3"))

    cmds = [
        "set -euo pipefail",
        "ROOT=/opt/network-o11y-demo",
        "LAB=$ROOT/local",
        "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
        "export HOME=/root",
        'mkdir -p "$LAB/alloy" "$LAB/scripts" "$LAB/templates/k8s"',
    ]

    for rel in SYNC_RELS:
        dest = f"$ROOT/{rel}"
        cmds.append(f"echo {b64_file(rel)} | base64 -d > \"{dest}\"")
        if rel.endswith(".sh"):
            cmds.append(f"chmod +x \"{dest}\"")

    kv_lines = [
        f"  'GC_OTLP_URL_2': {env['GC_OTLP_URL_2']!r},",
        f"  'GC_OTLP_ACCOUNT_2': {env['GC_OTLP_ACCOUNT_2']!r},",
        f"  'GC_OTLP_KEY_2': {env['GC_OTLP_KEY_2']!r},",
    ]
    if extra3:
        kv_lines += [
            f"  'GC_OTLP_URL_3': {env['GC_OTLP_URL_3']!r},",
            f"  'GC_OTLP_ACCOUNT_3': {env['GC_OTLP_ACCOUNT_3']!r},",
            f"  'GC_OTLP_KEY_3': {env['GC_OTLP_KEY_3']!r},",
        ]
    kv_literal = "\n".join(kv_lines)
    upsert = f"""python3 - <<'PY'
from pathlib import Path
p = Path('/opt/network-o11y-demo/local/.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
kv = {{
{kv_literal}
}}
lines = text.splitlines(keepends=True)
out, seen = [], set()
for line in lines:
    s = line.strip()
    if s and not s.startswith('#') and '=' in s:
        k = s.split('=', 1)[0].strip()
        if k in kv:
            out.append(f'{{k}}={{kv[k]}}\\n'); seen.add(k); continue
    out.append(line if line.endswith('\\n') else line + '\\n')
missing = [k for k in kv if k not in seen]
if missing:
    block = ['# Extra Grafana Cloud OTLP sinks\\n'] + [f'{{k}}={{kv[k]}}\\n' for k in missing]
    insert_at = next((i + 1 for i, l in enumerate(out) if l.startswith('GC_OTLP_KEY=') and not l.startswith('GC_OTLP_KEY_2')), len(out))
    out[insert_at:insert_at] = block
p.write_text(''.join(out), encoding='utf-8')
p.chmod(0o600)
print('updated .env extra OTLP keys', sorted(kv))
PY"""

    cmds += [
        "sed -i 's/\\r$//' $LAB/scripts/*.sh || true",
        upsert,
        "bash $LAB/scripts/render-alloy-otlp-export.sh",
        "grep -q grafana_cloud_2 $LAB/alloy/otlp-export.generated.alloy",
        "grep -q grafana_cloud_3 $LAB/alloy/otlp-export.generated.alloy || true",
        "echo RENDER_OTLP_OK",
        # Refresh k8s manifests + secret + rollout
        "python3 $LAB/scripts/generate-k8s-telemetry.py",
        "bash $LAB/scripts/deploy-ktranslate-golden.sh",
        "kubectl -n network-lab rollout restart deployment/alloy",
        "kubectl -n network-lab rollout status deployment/alloy --timeout=180s",
        "kubectl -n network-lab get secret grafana-cloud-credentials -o json | python3 -c \"import json,sys; print('secret_keys', sorted(json.load(sys.stdin).get('data',{}).keys()))\"",
        "kubectl -n network-lab get cm alloy-config -o jsonpath='{.data.config\\.alloy}' | grep -c grafana_cloud_2 || true",
        "echo DONE_DUAL_OTLP",
    ]
    return cmds


def main() -> int:
    payload = {"commands": build_commands()}
    out = REPO / "local" / ".ssm-dual-otlp.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")

    cmd_id = aws(
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
        "--comment",
        "dual-otlp-alloy-redeploy",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    )
    print(f"command_id={cmd_id}")

    for _ in range(60):
        time.sleep(5)
        inv = json.loads(
            aws(
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
            )
        )
        status = inv.get("Status")
        print(f"status={status}")
        if status in ("Success", "Failed", "Cancelled", "TimedOut"):
            stdout = inv.get("StandardOutputContent") or ""
            stderr = inv.get("StandardErrorContent") or ""
            # Redact any accidental key material
            stdout = re.sub(r"glc_[A-Za-z0-9+/=_-]+", "glc_***", stdout)
            stderr = re.sub(r"glc_[A-Za-z0-9+/=_-]+", "glc_***", stderr)
            print(stdout[-6000:])
            if stderr:
                print("STDERR:", stderr[-3000:])
            return 0 if status == "Success" else 1
    print("timed out waiting for SSM")
    return 1


if __name__ == "__main__":
    sys.exit(main())
