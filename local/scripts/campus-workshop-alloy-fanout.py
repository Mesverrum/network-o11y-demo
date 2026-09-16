#!/usr/bin/env python3
"""Add workshop-stack OTLP sink to campus Alloy (us-east-2). Does not print secrets."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

PROFILE, REGION, IID = "mvr", "us-east-2", "i-08eaccaf566dda685"
ENV = Path(__file__).resolve().parents[1] / ".env"


def load_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def send(commands: list[str], timeout: int = 120) -> str:
    p = Path(__file__).resolve().parents[1] / "state" / "ssm-campus-alloy-fanout.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    proc = subprocess.run(
        [
            "aws", "--profile", PROFILE, "--region", REGION, "ssm", "send-command",
            "--instance-ids", IID, "--document-name", "AWS-RunShellScript",
            "--comment", "campus-alloy-workshop-otlp", "--timeout-seconds", str(timeout),
            "--parameters", f"file://{p}", "--query", "Command.CommandId", "--output", "text",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    p.unlink(missing_ok=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-600:])
    return proc.stdout.strip()


def main() -> int:
    env = load_env()
    url = env["GC_OTLP_URL_3"]
    account = env["GC_OTLP_ACCOUNT_3"]
    key = env["GC_OTLP_KEY_3"]
    upsert = f"""python3 - <<'PY'
from pathlib import Path
alloy = Path('/opt/network-o11y-campus/telemetry/config.alloy')
text = alloy.read_text(encoding='utf-8')
old = 'otelcol.exporter.otlphttp.grafana_cloud.input'
new = 'otelcol.exporter.otlphttp.grafana_cloud.input, otelcol.exporter.otlphttp.grafana_cloud_3.input'
if 'grafana_cloud_3' not in text:
    text = text.replace(old, new)
    text += '''

otelcol.exporter.otlphttp "grafana_cloud_3" {{
  client {{
    endpoint = env("GRAFANA_CLOUD_OTLP_ENDPOINT_3")
    auth     = otelcol.auth.basic.grafana_cloud_3.handler
  }}
}}

otelcol.auth.basic "grafana_cloud_3" {{
  username = env("GRAFANA_CLOUD_OTLP_USER_3")
  password = env("GRAFANA_CLOUD_OTLP_PASSWORD_3")
}}
'''
    alloy.write_text(text, encoding='utf-8')
    print('patched config.alloy')
else:
    print('config.alloy already has grafana_cloud_3')
envp = Path('/opt/network-o11y-campus/.env')
vals = {{
  'GRAFANA_CLOUD_OTLP_ENDPOINT_3': {url!r},
  'GRAFANA_CLOUD_OTLP_USER_3': {account!r},
  'GRAFANA_CLOUD_OTLP_PASSWORD_3': {key!r},
}}
lines = envp.read_text(encoding='utf-8').splitlines() if envp.exists() else []
seen = set()
out = []
for line in lines:
    if '=' in line and not line.strip().startswith('#'):
        k = line.split('=', 1)[0].strip()
        if k in vals:
            out.append(f'{{k}}={{vals[k]}}')
            seen.add(k)
            continue
    out.append(line)
for k, v in vals.items():
    if k not in seen:
        out.append(f'{{k}}={{v}}')
envp.write_text('\\n'.join(out).rstrip() + '\\n', encoding='utf-8')
print('updated campus .env extra OTLP keys')
PY"""
    cid = send(
        [
            upsert,
            "docker rm -f campus-workshop-alloy",
            "docker run -d --name campus-workshop-alloy --restart unless-stopped --network fixedips --ip 172.20.20.8 --env-file /opt/network-o11y-campus/.env -v /opt/network-o11y-campus/telemetry/config.alloy:/etc/alloy/config.alloy:ro grafana/alloy:v1.6.1 run --server.http.listen-addr=0.0.0.0:12345 --storage.path=/var/lib/alloy/data /etc/alloy/config.alloy --stability.level=experimental",
            "sleep 4",
            "docker inspect campus-workshop-alloy --format '{{.State.Status}} {{range $k,$v := .NetworkSettings.Networks}}{{$v.IPAddress}}{{end}}'",
            "grep -c grafana_cloud_3 /opt/network-o11y-campus/telemetry/config.alloy",
            "docker logs campus-workshop-alloy --tail 15 2>&1 | tr -cd '\\11\\12\\15\\40-\\176\\n' | grep -Eiv 'password|glc_|token' | tail -15",
        ]
    )
    print("cmd", cid)
    for _ in range(30):
        time.sleep(4)
        st = subprocess.run(
            [
                "aws", "--profile", PROFILE, "--region", REGION, "ssm",
                "get-command-invocation", "--command-id", cid, "--instance-id", IID,
                "--query", "Status", "--output", "text",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.strip()
        print(st)
        if st in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
    proc = subprocess.run(
        [
            "aws", "ssm", "get-command-invocation", "--profile", PROFILE, "--region", REGION,
            "--command-id", cid, "--instance-id", IID, "--output", "json",
        ],
        capture_output=True,
    )
    d = json.loads(proc.stdout.decode("utf-8", "replace"))
    print((d.get("StandardOutputContent") or "")[-2000:])
    err = d.get("StandardErrorContent") or ""
    if err:
        print("err", err[-800:])
    return 0 if d.get("Status") == "Success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
