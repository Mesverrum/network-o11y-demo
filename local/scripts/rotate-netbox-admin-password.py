#!/usr/bin/env python3
"""Rotate NetBox admin password + ensure public :8000 for Grafana Cloud Infinity.

Writes (gitignored):
  local/.env  → NETBOX_ADMIN_USER / NETBOX_ADMIN_PASSWORD / NETBOX_PUBLIC_URL
  colocated   → same keys in /opt/network-o11y-demo/local/.env

Does not print the full password.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import shutil
import string
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PROFILE, REGION = "mvr", "us-east-1"
INSTANCE_TAG = "network-o11y-demo-colocated-lab"
SG_ID = "sg-0d4a29db498435db0"
NB_PUBLIC = (
    "http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000"
)


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


def ssm_run(iid: str, script: str, timeout: int = 240) -> str:
    cid = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        iid,
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        json.dumps({"commands": [script]}),
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
        st = data.get("Status")
        if st in ("Success", "Failed", "Cancelled", "TimedOut"):
            out = data.get("StandardOutputContent") or ""
            err = data.get("StandardErrorContent") or ""
            if st != "Success":
                raise RuntimeError(f"SSM {st}: {err or out}")
            return out
    raise RuntimeError("ssm timeout")


def gen_password(n: int = 28) -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def upsert_env(path: Path, pairs: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    for k, v in pairs.items():
        line = f"{k}={v}"
        if re.search(rf"^{re.escape(k)}=.*$", text, flags=re.M):
            text = re.sub(rf"^{re.escape(k)}=.*$", line, text, count=1, flags=re.M)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"
    path.write_text(text, encoding="utf-8")


def ensure_sg_public() -> None:
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
        print("SG :8000 already allows 0.0.0.0/0 (Grafana Cloud Infinity)")
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
    print("SG opened 0.0.0.0/0:8000 for Grafana Cloud / Infinity")


def rotate_password(iid: str, password: str) -> None:
    b64 = base64.b64encode(password.encode()).decode("ascii")
    # Upload a small helper + run it (avoids quoting hell)
    helper = r'''#!/usr/bin/env python3
import base64, os, pathlib, re, subprocess, sys
pw = base64.b64decode(sys.argv[1]).decode()
nb_public = sys.argv[2]
stack = pathlib.Path("/opt/network-o11y-demo/local/netbox-oss/netbox-docker")
envf = pathlib.Path("/opt/network-o11y-demo/local/.env")
os.chdir(stack)
# Rotate Django password
py = r"""
import os
from django.contrib.auth import get_user_model
u = get_user_model().objects.filter(username='admin').first()
assert u is not None, 'admin missing'
u.set_password(os.environ['NB_PASS'])
u.save()
print('password_rotated_ok')
"""
env = os.environ.copy()
env["NB_PASS"] = pw
r = subprocess.run(
    ["docker", "compose", "exec", "-T", "-e", "NB_PASS", "netbox",
     "/opt/netbox/venv/bin/python", "/opt/netbox/netbox/manage.py", "shell", "-c", py],
    env=env, capture_output=True, text=True,
)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
if r.returncode != 0 or "password_rotated_ok" not in (r.stdout or ""):
    raise SystemExit(f"rotate failed rc={r.returncode}")
# Persist host .env
text = envf.read_text(encoding="utf-8") if envf.exists() else ""
pairs = {
    "NETBOX_ADMIN_USER": "admin",
    "NETBOX_ADMIN_PASSWORD": pw,
    "NETBOX_PUBLIC_URL": nb_public,
    "SUPERUSER_PASSWORD": pw,
}
for k, v in pairs.items():
    line = f"{k}={v}"
    if re.search(rf"^{re.escape(k)}=.*$", text, flags=re.M):
        text = re.sub(rf"^{re.escape(k)}=.*$", line, text, count=1, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
envf.write_text(text, encoding="utf-8")
print("colocated_env_updated")
'''
    hb64 = base64.b64encode(helper.encode()).decode("ascii")
    script = f"""
set -euo pipefail
echo '{hb64}' | base64 -d > /tmp/rotate-netbox-admin.py
python3 /tmp/rotate-netbox-admin.py '{b64}' '{NB_PUBLIC}'
rm -f /tmp/rotate-netbox-admin.py
"""
    out = ssm_run(iid, script)
    if "password_rotated_ok" not in out or "colocated_env_updated" not in out:
        raise RuntimeError(f"rotate failed: {out}")
    print("NetBox admin password rotated on colocated")


def verify_login_page() -> None:
    req = urllib.request.Request(f"{NB_PUBLIC}/login/", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"public UI reachable HTTP {resp.status}")


def main() -> int:
    pw = gen_password(28)
    iid = instance_id()
    print(f"instance={iid}")
    ensure_sg_public()
    rotate_password(iid, pw)
    upsert_env(
        ENV_PATH,
        {
            "NETBOX_ADMIN_USER": "admin",
            "NETBOX_ADMIN_PASSWORD": pw,
            "NETBOX_PUBLIC_URL": NB_PUBLIC,
        },
    )
    print(f"stored credentials in {ENV_PATH}")
    print(f"  NETBOX_ADMIN_USER=admin")
    print(f"  NETBOX_ADMIN_PASSWORD length={len(pw)} prefix={pw[:4]}…")
    verify_login_page()
    print(f"UI: {NB_PUBLIC}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
