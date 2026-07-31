#!/usr/bin/env bash
# Sanity checks for colocated ContainerLab fabric before telemetry starts.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

EXPECTED_SRL="${#SRL_NODES[@]}"
EXPECTED_ALL="${#ALL_FABRIC_NODES[@]}"

die()  { echo "ERROR: [fabric-sanity] $*" >&2; exit 1; }
info() { echo "==> [fabric-sanity] $*"; }

wait_sr_cli() {
  local n=$1 tries="${2:-90}"
  while (( tries-- > 0 )); do
    if docker exec "$n" sr_cli -ec 'show version' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

for n in "${SRL_NODES[@]}"; do
  cfg="${ROOT}/configs/fabric/${n}.cfg"
  [[ -f "$cfg" ]] || die "missing staged config ${cfg} (run stage-fabric-profile.sh)"
done

running="$(docker ps -q | wc -l | tr -d ' ')"
[[ "${running}" -ge "${EXPECTED_ALL}" ]] \
  || die "expected >=${EXPECTED_ALL} running containers, got ${running}"

for n in "${SRL_NODES[@]}"; do
  docker inspect "$n" >/dev/null 2>&1 || die "container ${n} missing"
  [[ "$(docker inspect -f '{{.State.Running}}' "$n")" == "true" ]] || die "${n} not running"
done

info "waiting for sr_cli on ${EXPECTED_SRL} SRL nodes..."
for n in "${SRL_NODES[@]}"; do
  wait_sr_cli "$n" 90 || die "${n}: sr_cli not ready"
  info "${n}: sr_cli OK"
done

if docker exec spine1 sr_cli -ec 'show network-instance default protocols bgp summary' 2>/dev/null \
  | grep -qE 'Total UP peers[[:space:]]*:[[:space:]]*[1-9]'; then
  info "BGP peers up on spine1"
else
  info "BGP not fully converged (continuing — SNMP may still work)"
fi

info "fabric sanity passed (${EXPECTED_SRL} SRL + $(( EXPECTED_ALL - EXPECTED_SRL )) clients)"
