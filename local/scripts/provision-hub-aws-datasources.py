#!/usr/bin/env python3
"""Add Grafana Cloud datasources to the AWS hub Grafana.

The dev Grafana is the hub-grafana container on the colocated EC2 (NLB :3000).
This does not start anything on the laptop.

- networko11ydev (GRAFANA_TOKEN_2): grafanacloud-prom (default), grafanacloud-logs, grafanacloud-traces
- marcnetterfield1 (GRAFANA_TOKEN): mf1-prom, mf1-logs. hub-canary exports here, so the
  bundled Instrumentation Hub dashboards read these.

Tokens are uploaded to a private S3 object and deleted after the host reads them; they are
not printed. Existing datasources with the same UID are updated in place.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid

IID = "i-0639d827b3ecf3b82"
REGION = "us-east-1"
BUCKET = "mvr-net-o11y-xfer-494614287886"
REPO = pathlib.Path(__file__).resolve().parents[2]
ENV = REPO / "local" / ".env"
AWS_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

HOST = r"""#!/bin/bash
set -euo pipefail
trap 'rm -f /root/hub-ds/tokens.json' EXIT
mkdir -p /root/hub-ds
curl -fsSL -o /root/hub-ds/tokens.json '__URL__'
chmod 600 /root/hub-ds/tokens.json
python3 - <<'PY'
import json, urllib.request, urllib.parse, urllib.error
tokens = json.load(open("/root/hub-ds/tokens.json", encoding="utf-8"))
BASE = "http://127.0.0.1:3000"
N2 = "https://networko11ydev.grafana.net/api/datasources/proxy/uid/"
M1 = "https://marcnetterfield1.grafana.net/api/datasources/proxy/uid/"
specs = [
    ("prometheus", "grafanacloud-prom", "grafanacloud-networko11ydev-prom", True, N2 + "grafanacloud-prom", "n2", {"httpMethod": "POST"}),
    ("loki", "grafanacloud-logs", "grafanacloud-networko11ydev-logs", False, N2 + "grafanacloud-logs", "n2", {}),
    ("tempo", "grafanacloud-traces", "grafanacloud-networko11ydev-traces", False, N2 + "grafanacloud-traces", "n2", {}),
    ("prometheus", "mf1-prom", "marcnetterfield1-prom", False, M1 + "grafanacloud-prom", "m1", {"httpMethod": "POST"}),
    ("loki", "mf1-logs", "marcnetterfield1-logs", False, M1 + "grafanacloud-logs", "m1", {}),
]

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req)

for typ, uid, name, default, url, tok, extra in specs:
    body = {
        "name": name, "uid": uid, "type": typ, "access": "proxy", "url": url,
        "isDefault": default,
        "jsonData": {"httpHeaderName1": "Authorization", **extra},
        "secureJsonData": {"httpHeaderValue1": "Bearer " + tokens[tok]},
    }
    try:
        call("GET", "/api/datasources/uid/" + uid)
        exists = True
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        exists = False
    try:
        if exists:
            resp = call("PUT", "/api/datasources/uid/" + uid, body)
        else:
            resp = call("POST", "/api/datasources", body)
        print(f"{'updated' if exists else 'created'} {typ} {uid} http={resp.status}")
    except urllib.error.HTTPError as e:
        print(f"{typ} {uid} http={e.code} {e.read().decode('utf-8', 'replace')[:180]}")
        raise SystemExit(1)

for uid, expr in [("grafanacloud-prom", "count(discovery_snmp_device_info)"),
                  ("mf1-prom", 'count(discovery_snmp_device_info{collector="hub-canary"})')]:
    q = urllib.parse.urlencode({"query": expr})
    prom = json.load(call("GET", f"/api/datasources/proxy/uid/{uid}/api/v1/query?" + q))
    res = prom["data"]["result"]
    print(uid, expr, res[0]["value"][1] if res else "0")
for uid in ("grafanacloud-logs", "mf1-logs"):
    print(uid, call("GET", f"/api/datasources/proxy/uid/{uid}/loki/api/v1/labels").status)
print("grafanacloud-traces", call("GET", "/api/datasources/proxy/uid/grafanacloud-traces/api/echo").status)
PY
"""


def load_tokens() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    out = {"n2": values.get("GRAFANA_TOKEN_2", ""), "m1": values.get("GRAFANA_TOKEN", "")}
    for key, env in (("n2", "GRAFANA_TOKEN_2"), ("m1", "GRAFANA_TOKEN")):
        if not out[key]:
            sys.exit(f"{env} is unset in local/.env")
    return out


def aws(*args: str) -> str:
    return subprocess.check_output(
        ["aws", "--profile", "mvr", "--region", REGION, *args],
        text=True, encoding="utf-8", errors="replace", env=AWS_ENV,
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tokens = load_tokens()
    key = f"hub-ds/{uuid.uuid4().hex}/tokens.json"
    token_file = REPO / "local" / ".hub-ds-tokens.json"
    params = REPO / "local" / ".ssm-hub-ds.json"
    try:
        token_file.write_text(json.dumps(tokens), encoding="utf-8", newline="\n")
        aws("s3", "cp", str(token_file), f"s3://{BUCKET}/{key}")
        url = aws("s3", "presign", f"s3://{BUCKET}/{key}", "--expires-in", "600").strip()
        script = HOST.replace("__URL__", url)
        b64 = base64.b64encode(script.encode()).decode()
        params.write_text(json.dumps({"commands": [
            f"echo {b64} | base64 -d > /tmp/hub-ds.sh",
            "bash /tmp/hub-ds.sh",
            "rm -f /tmp/hub-ds.sh",
        ]}), encoding="utf-8")
        cmd_id = aws(
            "ssm", "send-command", "--instance-ids", IID, "--document-name", "AWS-RunShellScript",
            "--timeout-seconds", "180", "--parameters", f"file://{params.as_posix()}",
            "--query", "Command.CommandId", "--output", "text",
        ).strip()
        print(f"command {cmd_id}", flush=True)
        for _ in range(24):
            time.sleep(5)
            inv = json.loads(aws(
                "ssm", "get-command-invocation", "--command-id", cmd_id,
                "--instance-id", IID, "--output", "json",
            ))
            status = inv.get("Status")
            print(f"status={status}", flush=True)
            if status in {"Success", "Failed", "Cancelled", "TimedOut"}:
                print(inv.get("StandardOutputContent") or "")
                err = inv.get("StandardErrorContent") or ""
                if err:
                    print("STDERR:", err[-1500:])
                if status != "Success":
                    raise SystemExit(1)
                return
        raise SystemExit("timed out")
    finally:
        token_file.unlink(missing_ok=True)
        params.unlink(missing_ok=True)
        subprocess.run(
            ["aws", "--profile", "mvr", "--region", REGION, "s3", "rm", f"s3://{BUCKET}/{key}"],
            check=False, env=AWS_ENV,
        )


if __name__ == "__main__":
    main()
