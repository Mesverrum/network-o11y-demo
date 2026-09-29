#!/usr/bin/env python3
"""Ship the Instrumentation Hub app to the AWS hub Grafana and build it there.

Nothing is built on the laptop. The plugin source is tarred to a private S3 object, and the
colocated EC2 host typechecks and builds it in node:22, restarts hub-grafana, and imports the
bundled dashboards. With --e2e it runs tests/fleetScenario.spec.ts in a Playwright container on
the host; that spec clicks Apply, which writes the real Fleet pipeline for hub-canary.

  python3 local/scripts/hub-app-ship.py [--e2e]
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
APP = "mesverrum-networkinstrumentationhub-app"
PLUGIN = REPO / "grafana" / APP
HOST_DIR = f"/opt/src/network-o11y-demo/grafana/{APP}"
SHIP = ["src", "tests", "scripts", "playwright.config.ts", "package.json", "tsconfig.json"]
AWS_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

HOST = r"""#!/bin/bash
set -euo pipefail
D=__DIR__
APP=__APP__
curl -fsSL -o /tmp/hub-src.tgz '__URL__'
rm -rf "$D/src" "$D/tests"
tar -xzf /tmp/hub-src.tgz -C "$D"
rm -f /tmp/hub-src.tgz
echo "== typecheck + build"
docker run --rm -v "$D:/app" -w /app node:22 bash -c 'npm run typecheck && npm run build' 2>&1 | tail -8
test -f "$D/dist/dashboards/fleet-rollout.json"
docker restart hub-grafana >/dev/null
for i in $(seq 1 30); do curl -sf localhost:3000/api/health >/dev/null && break; sleep 2; done
echo "== import dashboards"
python3 - <<'PY'
import json, urllib.request
app = "__APP__"
for path in ("dashboards/fleet-rollout.json", "dashboards/discovery.json", "dashboards/data-arriving.json"):
    body = {"pluginId": app, "path": path, "overwrite": True, "inputs": []}
    req = urllib.request.Request("http://127.0.0.1:3000/api/dashboards/import", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    res = json.load(urllib.request.urlopen(req))
    print(" ", path, "->", res.get("uid") or res.get("importedUri"), res.get("imported"))
PY
if [ "__E2E__" = "1" ]; then
  echo "== e2e (Playwright on this host)"
  PW=$(docker run --rm -v "$D:/app" -w /app node:22 node -p "require('@playwright/test/package.json').version")
  mkdir -p "$D/playwright/.auth"
  echo '{"cookies":[],"origins":[]}' > "$D/playwright/.auth/admin.json"
  set +e
  docker run --rm --network host --ipc=host -v "$D:/app" -w /app \
    -e GRAFANA_URL=http://127.0.0.1:3000 -e HUB_E2E_FLEET=1 \
    "mcr.microsoft.com/playwright:v${PW}-noble" \
    npx playwright test --project=chromium --no-deps --reporter=line tests/appNavigation.spec.ts tests/fleetScenario.spec.ts 2>&1 | tail -40
  RC=${PIPESTATUS[0]}
  set -e
  echo "e2e exit=$RC"
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
    return buf.getvalue()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", action="store_true", help="run the Fleet scenario spec on the host")
    args = ap.parse_args()

    key = f"hub-ship/{uuid.uuid4().hex}/src.tgz"
    tgz = REPO / "local" / ".hub-src.tgz"
    params = REPO / "local" / ".ssm-hub-ship.json"
    try:
        tgz.write_bytes(pack())
        aws("s3", "cp", str(tgz), f"s3://{BUCKET}/{key}")
        url = aws("s3", "presign", f"s3://{BUCKET}/{key}", "--expires-in", "900").strip()
        script = (HOST.replace("__URL__", url).replace("__DIR__", HOST_DIR).replace("__APP__", APP)
                  .replace("__E2E__", "1" if args.e2e else "0"))
        b64 = base64.b64encode(script.encode()).decode()
        params.write_text(json.dumps({"commands": [
            f"echo {b64} | base64 -d > /tmp/hub-ship.sh",
            "bash /tmp/hub-ship.sh",
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
