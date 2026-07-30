#!/usr/bin/env bash
# Recover SRL fabric + SNMP after long idle / net_inst_mgr wedge (WSL drvfs safe).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "${ROOT}/scripts/lab-path.sh"

NODES=(spine1 leaf1 leaf2)

wait_sr_cli() {
  local n=$1 tries="${2:-90}"
  while (( tries-- > 0 )); do
    docker exec "$n" sr_cli -ec 'show version' >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "ERROR: ${n} sr_cli not ready" >&2
  return 1
}

apply_full() {
  local n=$1 cfg=$2
  {
    echo 'enter candidate'
    grep -vE '^\s*#' "$cfg" | grep -vE '^\s*$' || true
    echo 'commit stay'
  } | docker exec -i "$n" sr_cli
}

bash "${ROOT}/scripts/sync-clab-workdir.sh"

for n in "${NODES[@]}"; do
  docker start "$n" 2>/dev/null || true
done
sleep 45
for n in "${NODES[@]}"; do wait_sr_cli "$n"; done

for n in "${NODES[@]}"; do
  cfg="${CLAB_DEPLOY_DIR}/configs/fabric/${n}.cfg"
  [[ -f "$cfg" ]] || cfg="${ROOT}/configs/fabric/${n}.cfg"
  echo "==> full apply ${n}"
  apply_full "$n" "$cfg" || {
    echo "WARN: full apply failed on ${n}, restarting..."
    docker restart "$n"
    sleep 60
    wait_sr_cli "$n"
    apply_full "$n" "$cfg" || echo "WARN: ${n} still failing"
  }
done

bash "${ROOT}/scripts/update-snmp-targets.sh"
make generate
make discover GROUP=srl
bash "${ROOT}/scripts/reload-ktranslate-devices.sh"
bash "${ROOT}/scripts/post-telemetry-config.sh"
make traffic

for n in "${NODES[@]}"; do
  echo "=== ${n} snmp oper-state ==="
  docker exec "$n" sr_cli -ec 'info from state system snmp network-instance mgmt oper-state' || true
done

echo "==> recovery script done"
