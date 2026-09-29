#!/usr/bin/env python3
"""Ship the Network Devices app to the AWS hub Grafana and build it there.

Nothing is built on the laptop. Source is tarred to a private S3 object. The colocated host
typechecks the river editor, builds the plugin with the hub app's node_modules, and restarts
hub-grafana. With --e2e it runs tests/deviceProfile.spec.ts on the host. That spec writes a
name override onto one hub-canary device and then clears it. A cleanup pass strips any leftover
e2e-pin override.

  python3 local/scripts/devices-app-ship.py [--e2e]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import time
import uuid

IID = "i-0639d827b3ecf3b82"
REGION = "us-east-1"
BUCKET = "mvr-net-o11y-xfer-494614287886"
REPO = pathlib.Path(__file__).resolve().parents[2]
APP = "mesverrum-networkdevices-app"
PLUGIN = REPO / "grafana" / APP
HUB_APP = "mesverrum-networkinstrumentationhub-app"
SPEC = REPO / "grafana" / HUB_APP / "tests" / "deviceProfile.spec.ts"
HOST_DIR = f"/opt/src/network-o11y-demo/grafana/{APP}"
HUB_DIR = f"/opt/src/network-o11y-demo/grafana/{HUB_APP}"
SHIP = ["src", "scripts", "package.json", "tsconfig.json"]
HUB_PLUGIN_JSON = REPO / "grafana" / HUB_APP / "src" / "plugin.json"
AWS_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

HOST = r"""#!/bin/bash
set -euo pipefail
D=__DIR__
HUB=__HUB__
curl -fsSL -o /tmp/devices-src.tgz '__URL__'
rm -rf /tmp/devship
mkdir -p /tmp/devship
tar -xzf /tmp/devices-src.tgz -C /tmp/devship
rm -rf "$D/src" "$D/scripts"
cp -a /tmp/devship/src "$D/src"
cp -a /tmp/devship/scripts "$D/scripts"
cp /tmp/devship/package.json /tmp/devship/tsconfig.json "$D/"
cp /tmp/devship/deviceProfile.spec.ts "$HUB/tests/deviceProfile.spec.ts"
rm -f /tmp/devices-src.tgz
echo "== river check"
docker run --rm -v "$D:/app" -w /app node:22 node --experimental-strip-types scripts/river-check.mts
echo "== build"
# Mount the hub toolchain; a symlink to $HUB from inside the devices bind-mount is invisible in the container.
docker run --rm \
  -v "$D:/app" \
  -v "$HUB/node_modules:/app/node_modules" \
  -v "$HUB/.config:/app/.config" \
  -w /app node:22 \
  bash -c './node_modules/.bin/webpack -c ./.config/webpack/webpack.config.ts --env production' 2>&1 | tail -20
test -f "$D/dist/module.js"
# Hub plugin needs the canary-http proxy route for the collector catalog.
if [ -f /tmp/devship/hub-plugin.json ]; then
  cp /tmp/devship/hub-plugin.json "$HUB/src/plugin.json"
  docker run --rm -v "$HUB:/app" -w /app node:22 bash -c 'npm run build' 2>&1 | tail -8
fi
docker restart hub-grafana >/dev/null
for i in $(seq 1 30); do curl -sf localhost:3000/api/health >/dev/null && break; sleep 2; done
# Smoke: Grafana can reach the canary fingerprints via the new proxy route.
curl -sf -m 8 "http://127.0.0.1:3000/api/plugin-proxy/mesverrum-networkinstrumentationhub-app/canary-http/api/v0/component/remotecfg/hub_hub_demo.default/discovery.snmp.hub/fingerprints" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin); print("proxy catalog", d.get("library_hash"), len(d.get("profiles") or []))' \
  || echo "proxy catalog not ready yet"
if [ "__E2E__" = "1" ]; then
  echo "== e2e (Playwright on this host)"
  PW=$(docker run --rm -v "$HUB:/app" -w /app node:22 node -p "require('@playwright/test/package.json').version")
  mkdir -p "$HUB/playwright/.auth"
  echo '{"cookies":[],"origins":[]}' > "$HUB/playwright/.auth/admin.json"
  set +e
  docker run --rm --network host --ipc=host -v "$HUB:/app" -w /app \
    -e GRAFANA_URL=http://127.0.0.1:3000 -e HUB_E2E_FLEET=1 \
    "mcr.microsoft.com/playwright:v${PW}-noble" \
    npx playwright test --project=chromium --no-deps --reporter=line tests/deviceProfile.spec.ts 2>&1 | tail -50
  RC=${PIPESTATUS[0]}
  set -e
  echo "e2e exit=$RC"
  python3 - <<'PY'
import json, re, urllib.request
base = "http://127.0.0.1:3000/api/plugin-proxy/mesverrum-networkinstrumentationhub-app/fleet/pipeline.v1.PipelineService/"

def post(rpc, body):
    req = urllib.request.Request(base + rpc, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Grafana-Org-Id": "1"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)

def revision_of(text):
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"

def restamp(river):
    slot = "__HUB_REVISION__"
    if 'target_label = "hub_revision"' not in river:
        return river
    with_slot, n = re.subn(
        r'(target_label = "hub_revision"\s+replacement\s+= ")(?:[0-9a-f]{8}|__HUB_REVISION__)(")',
        lambda m: m.group(1) + slot + m.group(2),
        river, count=1)
    if n != 1:
        return river
    return with_slot.replace(slot, revision_of(with_slot), 1)

try:
    data = post("ListPipelines", {})
except Exception as exc:
    print("cleanup skipped:", exc)
    raise SystemExit(0)
pipes = data.get("pipelines") or data.get("items") or []
left = False
for p in pipes:
    contents = p.get("contents") or ""
    if "e2e-pin" not in contents:
        continue
    left = True
    cleaned = re.sub(r"[ \t]*override\s*\{[^}]*e2e-pin[^}]*\}[ \t]*\n?", "", contents)
    if cleaned == contents:
        print("could not strip e2e-pin from", p.get("name"))
        continue
    cleaned = restamp(cleaned)
    post("UpsertPipeline", {"pipeline": {"name": p["name"], "contents": cleaned,
                                         "matchers": p.get("matchers") or [], "enabled": p.get("enabled", True)}})
    print("stripped e2e-pin from", p.get("name"))
if not left:
    print("cleanup: no e2e-pin left")
PY
  exit "$RC"
fi
"""


def aws(*args: str) -> str:
    return subprocess.check_output(
        ["aws", "--profile", "mvr", "--region", REGION, *args],
        text=True, encoding="utf-8", errors="replace", env=AWS_ENV,
    )


def pack() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in SHIP:
            path = PLUGIN / rel
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for f in files:
                data = f.read_bytes()
                info = tarfile.TarInfo(f.relative_to(PLUGIN).as_posix())
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        spec = SPEC.read_bytes()
        info = tarfile.TarInfo("deviceProfile.spec.ts")
        info.size = len(spec)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(spec))
        hub = HUB_PLUGIN_JSON.read_bytes()
        info = tarfile.TarInfo("hub-plugin.json")
        info.size = len(hub)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(hub))
    return buf.getvalue()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", action="store_true", help="run the device profile spec on the host")
    args = ap.parse_args()

    key = f"devices-ship/{uuid.uuid4().hex}/src.tgz"
    tgz = REPO / "local" / ".devices-src.tgz"
    params = REPO / "local" / ".ssm-devices-ship.json"
    try:
        tgz.write_bytes(pack())
        aws("s3", "cp", str(tgz), f"s3://{BUCKET}/{key}")
        url = aws("s3", "presign", f"s3://{BUCKET}/{key}", "--expires-in", "900").strip()
        script = (HOST.replace("__URL__", url).replace("__DIR__", HOST_DIR).replace("__HUB__", HUB_DIR)
                  .replace("__E2E__", "1" if args.e2e else "0"))
        b64 = base64.b64encode(script.encode()).decode()
        params.write_text(json.dumps({"commands": [
            f"echo {b64} | base64 -d > /tmp/devices-ship.sh",
            "bash /tmp/devices-ship.sh",
        ]}), encoding="utf-8")
        cmd_id = aws(
            "ssm", "send-command", "--instance-ids", IID, "--document-name", "AWS-RunShellScript",
            "--timeout-seconds", "1800", "--parameters", f"file://{params.as_posix()}",
            "--query", "Command.CommandId", "--output", "text",
        ).strip()
        print(f"command {cmd_id}", flush=True)
        deadline = time.time() + 1900
        while time.time() < deadline:
            time.sleep(10)
            inv = json.loads(aws("ssm", "get-command-invocation", "--command-id", cmd_id,
                                 "--instance-id", IID, "--output", "json"))
            status = inv.get("Status")
            if status in {"Success", "Failed", "Cancelled", "TimedOut"}:
                print(f"status={status}")
                print(inv.get("StandardOutputContent") or "")
                err = inv.get("StandardErrorContent") or ""
                if err:
                    print("STDERR:", err[-2000:])
                if status != "Success":
                    raise SystemExit(1)
                return
        raise SystemExit("timed out")
    finally:
        tgz.unlink(missing_ok=True)
        params.unlink(missing_ok=True)
        subprocess.run(["aws", "--profile", "mvr", "--region", REGION, "s3", "rm", f"s3://{BUCKET}/{key}"],
                       check=False, env=AWS_ENV, capture_output=True)


if __name__ == "__main__":
    main()
