#!/usr/bin/env bash
# Recover SRL fabric only (no collectors). Start stopped nodes or redeploy if missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

SRL=(spine1 leaf1 leaf2)

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }

srl_running() {
  local n
  for n in "${SRL[@]}"; do
    [[ "$(docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null || echo false)" == "true" ]] || return 1
  done
  return 0
}

srl_exist() {
  local n
  for n in "${SRL[@]}"; do
    docker inspect "$n" >/dev/null 2>&1 || return 1
  done
  return 0
}

wait_sr_cli() {
  local n=$1 tries="${2:-45}"
  while (( tries-- > 0 )); do
    if docker exec "$n" sr_cli -ec 'show version' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

bgp_peers_up() {
  local out
  out="$(docker exec spine1 sr_cli -ec 'show network-instance default protocols bgp summary' 2>/dev/null || true)"
  grep -qE 'Total UP peers[[:space:]]*:[[:space:]]*[1-9]' <<<"$out"
}

if ! srl_exist; then
  info "SRL containers missing — deploying topology..."
  bash "${ROOT}/scripts/clab.sh" deploy
elif ! srl_running; then
  info "Starting stopped SRL nodes..."
  for n in "${SRL[@]}"; do
    if [[ "$(docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null || echo false)" != "true" ]]; then
      docker start "$n" >/dev/null
    fi
  done
else
  info "SRL nodes already running"
  exit 0
fi

info "Waiting for SR Linux (up to 90s)..."
for n in "${SRL[@]}"; do
  wait_sr_cli "$n" 45 || warn "${n}: sr_cli slow — continuing"
done

sleep 15

if bgp_peers_up; then
  info "BGP peers up — fabric OK"
  exit 0
fi

warn "BGP not converged — applying fabric config..."
if ! bash "${ROOT}/scripts/apply-fabric-config.sh"; then
  warn "fabric-apply had errors — nodes may still be booting"
  exit 1
fi

info "Fabric stabilized."
