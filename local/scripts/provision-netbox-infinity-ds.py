#!/usr/bin/env python3
"""Provision NetBox Infinity datasource + open SG for Grafana Cloud proxy access.

- Syncs NETBOX_TOKEN from colocated host into local/.env (no stdout of secret)
- Allows TCP/8000 from 0.0.0.0/0 on colocated SG (lab; token still required for API)
- Creates/updates Grafana Infinity datasource uid=netbox-api
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PROFILE, REGION = "mvr", "us-east-1"
INSTANCE_TAG = "network-o11y-demo-colocated-lab"
SG_ID = "sg-0d4a29db498435db0"
NB_HOST = "network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com"
NB_URL = f"http://{NB_HOST}:8000"
DS_UID = "netbox-api"
DS_NAME = "NetBox API (Infinity)"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def aws(*args: str) -> str:
    exe = shutil.which("aws") or shutil.which("aws.exe") or "aws"
    return subprocess.check_output(
        [exe, "--profile", PROFILE, "--region", REGION, *args],
        text=True,
        encoding="utf-8",
        errors="replace",
    )


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
        raise RuntimeError("no colocated instance")
    return out


def ssm_run(iid: str, script: str, timeout: int = 180) -> str:
    params = {"commands": [script]}
    cid = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        iid,
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        json.dumps(params),
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ).strip()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(4)
        data = json.loads(
            aws(
                "ssm",
                "get-command-invocation",
                "--command-id",
                cid,
                "--instance-id",
                iid,
                "--output",
                "json",
            )
        )
        if data.get("Status") in ("Success", "Failed", "Cancelled", "TimedOut"):
            if data.get("Status") != "Success":
                raise RuntimeError(data.get("StandardErrorContent") or data.get("Status"))
            return data.get("StandardOutputContent") or ""
    raise RuntimeError("ssm timeout")


def sync_token_from_colocated(iid: str) -> str:
    out = ssm_run(
        iid,
        r"""
set -e
LAB=/opt/network-o11y-demo/local
tok=$(grep -E '^NETBOX_TOKEN=' "$LAB/.env" | head -1 | cut -d= -f2- | tr -d '\r' | tr -d '"' | tr -d "'")
# emit only marker+token for parser (agent must not print)
printf 'TOKEN<<%s\n' "$tok"
""",
    )
    m = re.search(r"TOKEN<<(.*)$", out.strip(), re.S)
    if not m:
        raise RuntimeError("could not parse colocated NETBOX_TOKEN")
    tok = m.group(1).strip()
    if not tok.startswith("nbt_") and not tok:
        raise RuntimeError("unexpected token shape from colocated")
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    line = f"NETBOX_TOKEN={tok}"
    if re.search(r"^NETBOX_TOKEN=.*$", text, flags=re.M):
        text = re.sub(r"^NETBOX_TOKEN=.*$", line, text, count=1, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    # also ensure public URL hint
    if not re.search(r"^NETBOX_PUBLIC_URL=", text, flags=re.M):
        text += f"NETBOX_PUBLIC_URL={NB_URL}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    print(f"synced NETBOX_TOKEN from colocated (prefix={tok[:6]}… len={len(tok)})")
    return tok


def ensure_sg_open() -> None:
    raw = aws(
        "ec2",
        "describe-security-groups",
        "--group-ids",
        SG_ID,
        "--query",
        "SecurityGroups[0].IpPermissions[?FromPort==`8000`].IpRanges[].CidrIp",
        "--output",
        "json",
    )
    cidrs = json.loads(raw)
    if "0.0.0.0/0" in cidrs:
        print("SG already allows 0.0.0.0/0 on :8000")
        return
    aws(
        "ec2",
        "authorize-security-group-ingress",
        "--group-id",
        SG_ID,
        "--ip-permissions",
        json.dumps(
            [
                {
                    "IpProtocol": "tcp",
                    "FromPort": 8000,
                    "ToPort": 8000,
                    "IpRanges": [
                        {
                            "CidrIp": "0.0.0.0/0",
                            "Description": "Lab Grafana Cloud Infinity NetBox API",
                        }
                    ],
                }
            ]
        ),
    )
    print("SG opened 0.0.0.0/0:8000 for Infinity (lab)")


def grafana_api(env: dict[str, str], method: str, path: str, body: object | None = None):
    base = env["GRAFANA_URL"].rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def upsert_infinity_ds(env: dict[str, str], token: str) -> None:
    payload = {
        "uid": DS_UID,
        "name": DS_NAME,
        "type": "yesoreyeram-infinity-datasource",
        "access": "proxy",
        "url": NB_URL,
        "basicAuth": False,
        "jsonData": {
            "auth_method": "bearerToken",
            "allowedHosts": [NB_HOST, f"{NB_HOST}:8000", NB_URL],
            "oauthPassThru": False,
            "allowDangerousHTTPMethods": False,
        },
        "secureJsonData": {"bearerToken": token},
    }
    code, existing = grafana_api(env, "GET", f"/api/datasources/uid/{DS_UID}")
    if code == 200 and isinstance(existing, dict):
        payload["id"] = existing["id"]
        code2, out = grafana_api(env, "PUT", f"/api/datasources/{existing['id']}", payload)
        action = "updated"
    else:
        code2, out = grafana_api(env, "POST", "/api/datasources", payload)
        action = "created"
    if code2 not in (200, 201):
        raise RuntimeError(f"datasource {action} failed HTTP {code2}: {out}")
    print(f"{action} datasource uid={DS_UID} name={DS_NAME}")


def probe_public(token: str) -> None:
    req = urllib.request.Request(
        f"{NB_URL}/api/dcim/devices/?name=spine1&limit=1",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    n = len(body.get("results") or [])
    print(f"public API probe OK results={n} count={body.get('count')}")


def main() -> int:
    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("GRAFANA_URL/TOKEN required")
    iid = instance_id()
    print("instance", iid)
    tok = sync_token_from_colocated(iid)
    ensure_sg_open()
    # SG changes can take a few seconds to apply on NLB
    time.sleep(3)
    probe_public(tok)
    upsert_infinity_ds(env, tok)
    print("done — use datasource uid netbox-api in panels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
