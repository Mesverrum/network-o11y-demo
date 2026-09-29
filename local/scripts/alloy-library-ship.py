#!/usr/bin/env python3
"""Sync discovery.snmp library changes to EC2, rebuild network-dev, restart hub-canary.

Nothing is built on the laptop. Source under alloy/internal/component/discovery/snmp is
tarred to S3; the host overlays it onto /opt/src/alloy and runs build-alloy-bin-overlay.sh.
"""
from __future__ import annotations

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
ALLOY = REPO.parent / "alloy" / "internal" / "component" / "discovery" / "snmp"
AWS_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

HOST = r"""#!/bin/bash
set -euo pipefail
curl -fsSL -o /tmp/snmp-lib.tgz '__URL__'
rm -rf /tmp/snmp-ship
mkdir -p /tmp/snmp-ship
tar -xzf /tmp/snmp-lib.tgz -C /tmp/snmp-ship
cp -a /tmp/snmp-ship/. /opt/src/alloy/internal/component/discovery/snmp/
rm -f /tmp/snmp-lib.tgz
echo "== unit tests (library)"
docker run --rm -v /opt/src/alloy:/src -v /opt/src/snmp-sd:/snmp-sd -w /src \
  -v /home/ec2-user/.cache/alloy-gomod:/go/pkg/mod \
  -v /home/ec2-user/.cache/alloy-gobuild:/root/.cache/go-build \
  -e CGO_ENABLED=0 -e GOPROXY=https://proxy.golang.org,direct \
  golang:1.26.6 bash -c '
    set -euo pipefail
    git config --global --add safe.directory /src
    go mod edit -replace github.com/Mesverrum/snmp-sd=/snmp-sd
    ( cd collector && go mod edit -replace github.com/Mesverrum/snmp-sd=/snmp-sd )
    go test ./internal/component/discovery/snmp/ -count=1 -run "TestLoadFingerprintLibrary|TestAlloyConfig"
    git checkout -- go.mod go.sum collector/go.mod collector/go.sum
  ' 2>&1 | tail -30
echo "== rebuild image (inline; host build script may be stale)"
export ALLOY_SRC=/opt/src/alloy SNMPSD_SRC=/opt/src/snmp-sd
TAG=srl-local/alloy:network-dev
WORKDIR=/tmp/alloy-network-bin-$$
mkdir -p "$WORKDIR"
docker run --rm \
  -v "${ALLOY_SRC}:/src" -v "${SNMPSD_SRC}:/snmp-sd" \
  -v /home/ec2-user/.cache/alloy-gomod:/go/pkg/mod \
  -v /home/ec2-user/.cache/alloy-gobuild:/root/.cache/go-build \
  -w /src -e CGO_ENABLED=0 -e GOPROXY=https://proxy.golang.org,direct \
  golang:1.26.6 bash -c '
    set -euo pipefail
    git config --global --add safe.directory /src
    go mod edit -replace github.com/Mesverrum/snmp-sd=/snmp-sd
    ( cd collector && go mod edit -replace github.com/Mesverrum/snmp-sd=/snmp-sd )
    ( cd collector && go build -tags netgo -o ../build/alloy . )
    go build -o build/snmp-discovery github.com/Mesverrum/snmp-sd/cmd/snmp-discovery
    rm -rf build/snmp-lib
    mkdir -p build/snmp-lib
    cp -a /snmp-sd/snmp/. build/snmp-lib/
    git checkout -- go.mod go.sum collector/go.mod collector/go.sum
  ' 2>&1 | tail -20
cp -f "$ALLOY_SRC/build/alloy" "$ALLOY_SRC/build/snmp-discovery" "$WORKDIR/"
cp -a "$ALLOY_SRC/build/snmp-lib" "$WORKDIR/snmp-lib"
cat >"$WORKDIR/Dockerfile" <<'EOF'
FROM grafana/alloy:latest
COPY alloy /bin/alloy
COPY snmp-discovery /usr/bin/snmp-discovery
COPY snmp-lib/ /etc/alloy/
EOF
docker build -t "$TAG" "$WORKDIR" 2>&1 | tail -15
docker run --rm --entrypoint /bin/sh "$TAG" -c '
  for s in discovery_snmp_library_info discovery.snmp; do
    n=$(grep -a -c -F "$s" /bin/alloy || true)
    echo "$s $n"
    test "$n" -gt 0
  done
'
docker tag "$TAG" srl-local/alloy:network-dev-lib
docker save srl-local/alloy:network-dev-lib -o /tmp/alloy-lib.tar
k3s ctr images import /tmp/alloy-lib.tar
rm -f /tmp/alloy-lib.tar
rm -rf "$WORKDIR"
echo "== restart hub-canary"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl -n network-lab set image deploy/hub-canary alloy=srl-local/alloy:network-dev-lib
kubectl -n network-lab rollout restart deploy/hub-canary
kubectl -n network-lab rollout status deploy/hub-canary --timeout=180s
sleep 10
echo "== probe library metric + HTTP"
POD=$(kubectl -n network-lab get pod -l app=hub-canary --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
echo pod=$POD
kubectl -n network-lab exec "$POD" -- sh -c 'grep -a -c discovery_snmp_library_info /bin/alloy'
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  curl -sf -m 3 http://127.0.0.1:12347/-/ready >/dev/null && break
  sleep 3
done
curl -sf -m 5 http://127.0.0.1:12347/metrics | grep discovery_snmp_library_info | head -5 || echo 'metric not yet'
code=$(curl -s -o /tmp/fp.json -w "%{http_code}" -m 5 \
  "http://127.0.0.1:12347/api/v0/component/remotecfg/hub_hub_demo.default/discovery.snmp.hub/fingerprints" || echo err)
echo "GET fingerprints -> $code"
if [ "$code" = "200" ]; then
  python3 -c 'import json;d=json.load(open("/tmp/fp.json")); print("hash", d.get("library_hash"), "profiles", len(d.get("profiles") or []))'
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
        for f in sorted(ALLOY.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix not in {".go"} and f.name != "README.md":
                continue
            data = f.read_bytes()
            info = tarfile.TarInfo(f.relative_to(ALLOY).as_posix())
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not ALLOY.is_dir():
        raise SystemExit(f"missing {ALLOY}")
    key = f"alloy-snmp-ship/{uuid.uuid4().hex}/src.tgz"
    tgz = REPO / "local" / ".alloy-snmp-src.tgz"
    params = REPO / "local" / ".ssm-alloy-snmp-ship.json"
    try:
        tgz.write_bytes(pack())
        aws("s3", "cp", str(tgz), f"s3://{BUCKET}/{key}")
        url = aws("s3", "presign", f"s3://{BUCKET}/{key}", "--expires-in", "1800").strip()
        script = HOST.replace("__URL__", url)
        b64 = base64.b64encode(script.encode()).decode()
        params.write_text(json.dumps({"commands": [
            f"echo {b64} | base64 -d > /tmp/alloy-lib-ship.sh",
            "bash /tmp/alloy-lib-ship.sh",
        ]}), encoding="utf-8")
        cmd_id = aws(
            "ssm", "send-command", "--instance-ids", IID, "--document-name", "AWS-RunShellScript",
            "--timeout-seconds", "3600", "--parameters", f"file://{params.as_posix()}",
            "--query", "Command.CommandId", "--output", "text",
        ).strip()
        print(f"command {cmd_id}", flush=True)
        deadline = time.time() + 3700
        while time.time() < deadline:
            time.sleep(15)
            inv = json.loads(aws("ssm", "get-command-invocation", "--command-id", cmd_id,
                                 "--instance-id", IID, "--output", "json"))
            status = inv.get("Status")
            if status in {"Success", "Failed", "Cancelled", "TimedOut"}:
                print(f"status={status}")
                print(inv.get("StandardOutputContent") or "")
                err = inv.get("StandardErrorContent") or ""
                if err:
                    print("STDERR:", err[-3000:])
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
