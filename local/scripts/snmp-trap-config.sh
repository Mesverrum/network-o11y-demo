#!/usr/bin/env bash
# snmp-trap-config.sh — point SR Linux SNMP traps at the site-scoped SNMP poller
# (trap.listen port from groups/<site-group>.env TRAP_PORT).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=collector-runtime-ready.sh
source "${ROOT}/scripts/collector-runtime-ready.sh"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"

export_colocated_clab_host
CLAB_NET="${CLAB_NETWORK:-clab}"
DEVICES=("${SRL_NODES[@]}")

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

trap_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" snmp 2>/dev/null || true)"
if [[ -z "$trap_ip" || "$trap_ip" == "<no value>" ]]; then
  first_group="$(snmp_group_names "${ROOT}" | head -1)"
  [[ -n "${first_group}" ]] || die "no groups/*.env"
  cid="$(docker ps -qf "name=ktranslate_snmp_${first_group}" | head -1 || true)"
  [[ -n "$cid" ]] || die "SNMP collector not running — make up or set KTRANSLATE_CLAB_HOST"
  trap_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$cid" 2>/dev/null || true)"
fi
[[ -n "$trap_ip" && "$trap_ip" != "<no value>" ]] || die "SNMP collector not on network ${CLAB_NET}"

TRAP_COMMUNITY="$(awk -F= '/^TRAP_COMMUNITY=/{print $2; exit}' "${ROOT}/groups/"*.env 2>/dev/null | head -1)"
TRAP_COMMUNITY="${TRAP_COMMUNITY:-public}"

for d in "${DEVICES[@]}"; do
  docker inspect "$d" >/dev/null 2>&1 || die "container ${d} not found"
  TRAP_PORT="$(snmp_trap_port_for_node "${ROOT}" "${d}")"
  site="$(fabric_site_for_node "${d}")"
  info "Configuring SNMP traps on ${d} (site=${site}) -> ${trap_ip}:${TRAP_PORT}/udp"
  docker exec -i "$d" bash -c "sr_cli -ed" <<EOF
set / system snmp network-instance mgmt admin-state enable
set / system snmp trap-group ktranslate admin-state enable
set / system snmp trap-group ktranslate network-instance mgmt
set / system snmp trap-group ktranslate destination ktrans admin-state enable
set / system snmp trap-group ktranslate destination ktrans address ${trap_ip}
set / system snmp trap-group ktranslate destination ktrans port ${TRAP_PORT}
set / system snmp trap-group ktranslate destination ktrans security-level no-auth-no-priv
set / system snmp trap-group ktranslate destination ktrans community-entry lab-public community ${TRAP_COMMUNITY}
commit stay
EOF
done

info "Done. installedTraps (spine1):"
docker exec spine1 cat /etc/opt/srlinux/snmp/installedTraps 2>/dev/null | head -30 || \
  echo "(file not ready yet — appears after trap-group is active)"

info "Verify: make emit-events   or   make traps (synthetic)"
