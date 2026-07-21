#!/usr/bin/env bash
# Apply configs/fabric/*.cfg when clab postdeploy cannot commit from /mnt/c (WSL drvfs).
#
# On /mnt/c, full flat-config merge often fails (net_inst_mgr). Default: SNMP-only via
# enable-snmp-srl.sh. Set FULL_FABRIC=1 to attempt the full startup-config pipe first.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NODES=(spine1 leaf1 leaf2)

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }

wait_sr_cli() {
  local n=$1 tries=30
  while (( tries-- > 0 )); do
    if docker exec "$n" sr_cli -ec 'show version' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  die "${n}: sr_cli not ready after 60s"
}

restart_if_broken() {
  local n=$1
  if ! docker exec "$n" sr_cli -ec 'show version' >/dev/null 2>&1; then
    warn "${n}: restarting container after failed commit"
    docker restart "$n" >/dev/null
    wait_sr_cli "$n"
  fi
}

apply_full() {
  local n=$1 cfg=$2
  {
    echo 'enter candidate'
    grep -vE '^\s*#' "$cfg" | grep -vE '^\s*$' || true
    echo 'commit stay'
  } | docker exec -i "$n" sr_cli
}

for n in "${NODES[@]}"; do
  cfg="${ROOT}/configs/fabric/${n}.cfg"
  [[ -f "$cfg" ]] || die "missing ${cfg}"
  docker inspect "$n" >/dev/null 2>&1 || die "container ${n} not found"
  [[ "$(docker inspect -f '{{.State.Running}}' "$n")" == "true" ]] \
    || die "container ${n} is not running — start it first (docker start ${n})"

  wait_sr_cli "$n"

  if [[ "${FULL_FABRIC:-}" == "1" ]]; then
    info "Applying full fabric config to ${n}..."
    if ! apply_full "$n" "$cfg"; then
      warn "${n}: full fabric apply failed"
      restart_if_broken "$n"
    else
      continue
    fi
  fi

  info "Enabling SNMP on ${n}..."
  if ! bash "${ROOT}/scripts/enable-snmp-srl.sh" --node "$n"; then
    restart_if_broken "$n"
    bash "${ROOT}/scripts/enable-snmp-srl.sh" --node "$n"
  fi
done

info "Fabric/SNMP apply complete."
