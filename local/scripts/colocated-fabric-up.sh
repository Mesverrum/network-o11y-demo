#!/usr/bin/env bash
# Staggered ContainerLab deploy for colocated profile (5 SRL + 4 clients).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

STAGGER_SECS="${LAB_STAGGER_SECS:-20}"
SR_CLI_TRIES_SPINE="${LAB_SR_CLI_TRIES_SPINE:-90}"
SR_CLI_TRIES_LEAF="${LAB_SR_CLI_TRIES_LEAF:-120}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

wait_sr_cli() {
  local n=$1 tries="${2:-120}"
  while (( tries-- > 0 )); do
    local out
    out=$(docker exec "$n" sr_cli -ec 'show version' 2>&1) || true
    if grep -qi 'yang reload' <<<"$out"; then
      sleep 3
      continue
    fi
    if docker exec "$n" sr_cli -ec 'show version' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  die "${n}: sr_cli not ready"
}

stagger_wait() {
  info "settling ${STAGGER_SECS}s..."
  sleep "${STAGGER_SECS}"
}

info "Deploying colocated topology (${#SRL_NODES[@]} SRL + ${#CLIENT_NODES[@]} clients)..."
bash "${ROOT}/scripts/clab.sh" deploy

info "Staggered sr_cli readiness"
wait_sr_cli spine1 "${SR_CLI_TRIES_SPINE}"
info "spine1 ready"
stagger_wait

for n in "${SRL_NODES[@]}"; do
  [[ "$n" == "spine1" ]] && continue
  wait_sr_cli "$n" "${SR_CLI_TRIES_LEAF}"
  info "${n} ready"
  stagger_wait
done

info "Applying fabric / SNMP on SRL nodes..."
bash "${ROOT}/scripts/apply-fabric-config.sh"

bash "${ROOT}/scripts/colocated-fabric-sanity.sh"
info "colocated fabric deploy complete"
