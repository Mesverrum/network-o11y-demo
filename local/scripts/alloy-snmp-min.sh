#!/usr/bin/env bash
# alloy-snmp-min.sh — 1× SR Linux + Alloy SNMP only (no ktranslate, clients, or traffic).
#
# Tears down the 5-node Clos if it is running. Laptop topology.clab.yml is not overwritten.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export LAB_FABRIC_PROFILE=snmp-min
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "${ROOT}/.env")
  set +a
fi
# Re-assert after .env (fabric-nodes already honored the export; keep it).
export LAB_FABRIC_PROFILE=snmp-min

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }

clab_bin() {
  if command -v containerlab >/dev/null 2>&1; then
    echo containerlab
  else
    echo clab
  fi
}

wait_sr_cli() {
  local n=$1 tries="${2:-90}"
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

stop_heavy_sidecars() {
  bash "${ROOT}/scripts/fabric-watch.sh" stop || true
  bash "${ROOT}/scripts/events-loop.sh" stop || true
  bash "${ROOT}/scripts/traffic.sh" stop || true
  bash "${ROOT}/scripts/internet-probes.sh" stop || true
  local c
  for c in \
    ktranslate_flow ktranslate_sflow ktranslate_syslog \
    gnmic flow_dns topology_exporter \
    ktranslate_snmp_srl-hq ktranslate_snmp_srl-branch1 ktranslate_snmp_srl-branch2 \
    snmp_discovery \
    client1 client2 leaf1 leaf2 leaf-br1 leaf-br2 client-br1 client-br2
  do
    docker stop "$c" >/dev/null 2>&1 || true
    docker rm "$c" >/dev/null 2>&1 || true
  done
}

compose_alloy() {
  local args=(
    docker compose
    --env-file "${ROOT}/.env"
    --env-file "${ROOT}/compose-host.generated.env"
    --profile alloy-snmp
    -f "${ROOT}/compose-base.yaml"
  )
  [[ -f "${ROOT}/compose-groups.generated.yaml" ]] && args+=(-f "${ROOT}/compose-groups.generated.yaml")
  [[ -f "${ROOT}/compose-catalog.generated.yaml" ]] && args+=(-f "${ROOT}/compose-catalog.generated.yaml")
  [[ -f "${ROOT}/compose-limits.generated.yaml" ]] && args+=(-f "${ROOT}/compose-limits.generated.yaml")
  "${args[@]}" "$@"
}

cmd_up() {
  command -v docker >/dev/null || die "docker required"
  [[ -f "${ROOT}/.env" ]] || die "missing local/.env"
  docker image inspect "${ALLOY_IMAGE:-srl-local/alloy:network-dev}" >/dev/null 2>&1 \
    || die "image ${ALLOY_IMAGE:-srl-local/alloy:network-dev} not found — run: make alloy-network-image"

  info "Stopping traffic / extra collectors / extra fabric nodes..."
  stop_heavy_sidecars

  info "Destroying leftover Clos / min topologies..."
  bash "${ROOT}/scripts/clab.sh" destroy || true

  info "Deploying 1× SR Linux (spine1, SNMP only)..."
  export LAB_FABRIC_PROFILE=snmp-min
  bash "${ROOT}/scripts/clab.sh" deploy

  info "Waiting for sr_cli on spine1..."
  wait_sr_cli spine1
  bash "${ROOT}/scripts/enable-snmp-srl.sh" --node spine1

  info "Rendering Alloy SNMP overlay (LAB_ALLOY_SNMP=1, traps=1, syslog=1)..."
  mkdir -p "${ROOT}/alloy"
  export LAB_ALLOY_SNMP=1
  export LAB_ALLOY_SNMPTRAP=1
  export LAB_ALLOY_SYSLOG=1
  bash "${ROOT}/scripts/write-compose-host-env.sh"
  bash "${ROOT}/scripts/render-alloy-snmp-scrape.sh"
  bash "${ROOT}/scripts/render-alloy-snmp-trap.sh"

  info "Starting Alloy + snmp_discovery (no ktranslate / gnmic / flow)..."
  export SNMP_DISCOVERY_UID="$(id -u)"
  export SNMP_DISCOVERY_GID="$(id -g)"
  (cd "${ROOT}" && compose_alloy up -d --no-deps --force-recreate alloy)

  info "SNMP discovery (group file: CIDR + named auth)..."
  LAB_FABRIC_PROFILE=snmp-min bash "${ROOT}/scripts/alloy-snmp-discover.sh"
  (cd "${ROOT}" && compose_alloy up -d --no-deps --force-recreate snmp_discovery)

  info "Pointing spine1 traps at Alloy :1620 and syslog at Alloy :1514..."
  LAB_ALLOY_SNMPTRAP=1 bash "${ROOT}/scripts/snmp-trap-config.sh" || warn "trap-group apply failed"
  LAB_ALLOY_SYSLOG=1 bash "${ROOT}/scripts/syslog-config.sh" || warn "syslog apply failed"

  info ""
  info "snmp-min is up: spine1 + alloy (SNMP scrape + snmptrap + syslog join). No clients, no ktranslate."
  info "Targets:"
  cat "${ROOT}/alloy/snmp-targets.yml" || true
  info ""
  info "Tear down: make -C local alloy-snmp-min-down"
  info "Full Clos again: make -C local down && make -C local up"
}

cmd_down() {
  stop_heavy_sidecars
  docker stop alloy snmp_discovery >/dev/null 2>&1 || true
  docker rm alloy snmp_discovery >/dev/null 2>&1 || true
  if [[ -f "${ROOT}/compose-host.generated.env" ]]; then
    (cd "${ROOT}" && compose_alloy stop alloy snmp_discovery >/dev/null 2>&1) || true
    (cd "${ROOT}" && compose_alloy rm -f alloy snmp_discovery >/dev/null 2>&1) || true
  fi
  bash "${ROOT}/scripts/clab.sh" destroy || true
  info "snmp-min down"
}

cmd_status() {
  docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'NAMES|spine1|leaf|client|alloy|ktranslate|gnmic' || true
  if [[ -f "${ROOT}/alloy/snmp-targets.yml" ]]; then
    info "alloy/snmp-targets.yml:"
    cat "${ROOT}/alloy/snmp-targets.yml"
  fi
}

case "${1:-}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  *)
    echo "usage: $0 up|down|status" >&2
    exit 2
    ;;
esac
