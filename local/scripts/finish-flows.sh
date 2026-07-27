#!/usr/bin/env bash
# finish-flows.sh — apply fabric (if needed), softflowd, traffic, verify Grafana flows.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

info() { echo "==> $*"; }

if ! docker exec client2 ping -c 1 -W 2 172.17.0.1 >/dev/null 2>&1; then
  info "EVPN not ready — applying fabric..."
  for n in spine1 leaf1 leaf2; do
    docker exec "$n" sr_cli -ec 'discard stay' 2>/dev/null || true
  done
  for n in spine1 leaf1 leaf2; do
    bash scripts/apply-fabric-node.sh "$n"
  done
  for i in $(seq 1 12); do
    docker exec client2 ping -c 1 -W 2 172.17.0.1 >/dev/null 2>&1 && break
    sleep 10
  done
fi

docker exec client2 ping -c 2 -W 2 172.17.0.1

bash scripts/softflowd.sh
bash scripts/traffic.sh start

info "waiting 90s for ktranslate rollup..."
sleep 90

docker exec client1 softflowctl -c /var/run/softflowd.ctl statistics 2>/dev/null | head -12

python3 - <<'PY'
import json, urllib.parse, urllib.request
from pathlib import Path
env = {}
for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k] = v
url = env["GRAFANA_URL"]
token = env["GRAFANA_TOKEN"]
for q in ["count(network_io_by_flow_bytes)", "sum(network_io_by_flow_bytes) * 8 / 60"]:
    qs = urllib.parse.urlencode({"query": q})
    req = urllib.request.Request(
        f"{url}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{qs}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    results = data.get("data", {}).get("result", [])
    val = results[0]["value"][1] if results else "no data"
    print(f"  {q} => {val}")
PY
