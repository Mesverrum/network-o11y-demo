#!/usr/bin/env bash
# snmp-trap-config.sh — point SR Linux SNMP traps at ktranslate_snmp_srl
#
# Uses mgmt network-instance (same path SNMP polls use) and UDP port from
# groups/srl.env TRAP_PORT (default 1620) with TRAP_COMMUNITY (default public).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAB_NET="${CLAB_NETWORK:-clab}"
DEVICES=(spine1 leaf1 leaf2)
GROUP_ENV="${ROOT}/groups/srl.env"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

TRAP_PORT="$(awk -F= '/^TRAP_PORT=/{print $2; exit}' "${GROUP_ENV}" 2>/dev/null || echo 1620)"
TRAP_COMMUNITY="$(awk -F= '/^TRAP_COMMUNITY=/{print $2; exit}' "${GROUP_ENV}" 2>/dev/null || echo public)"

cid="$(docker ps -qf name=ktranslate_snmp_srl | head -1 || true)"
[[ -n "$cid" ]] || die "ktranslate_snmp_srl not running — make up first"

trap_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$cid" 2>/dev/null || true)"
[[ -n "$trap_ip" && "$trap_ip" != "<no value>" ]] || die "ktranslate_snmp_srl not on network ${CLAB_NET}"

info "Trap destination: ${trap_ip}:${TRAP_PORT}/udp (community ${TRAP_COMMUNITY}, network-instance mgmt)"

for d in "${DEVICES[@]}"; do
  docker inspect "$d" >/dev/null 2>&1 || die "container ${d} not found"
  info "Configuring SNMP traps on ${d}..."
  # community-entry name must differ from the community string (SR Linux rule).
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
