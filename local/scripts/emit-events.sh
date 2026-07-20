#!/usr/bin/env bash
# emit-events.sh — trigger real SR Linux traps + syslog toward ktranslate
#
# 1. Ensures syslog + SNMP trap destinations are configured
# 2. Briefly flaps leaf↔client links (and optionally a BGP session) so devices
#    emit linkDown/linkUp traps and interface/BGP syslog

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENSURE_CONFIG="${ENSURE_CONFIG:-1}"
FLAP_SECS="${FLAP_SECS:-5}"
DO_BGP="${DO_BGP:-1}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

if [[ "${ENSURE_CONFIG}" == "1" ]]; then
  info "Ensuring syslog + SNMP trap destinations..."
  bash "${ROOT}/scripts/syslog-config.sh"
  bash "${ROOT}/scripts/snmp-trap-config.sh"
fi

flap_iface() {
  local node="$1" iface="$2"
  info "Flap ${node} ${iface} (down ${FLAP_SECS}s → up)..."
  docker exec -i "$node" bash -c "sr_cli -ed" <<EOF
set / interface ${iface} admin-state disable
commit stay
EOF
  sleep "${FLAP_SECS}"
  docker exec -i "$node" bash -c "sr_cli -ed" <<EOF
set / interface ${iface} admin-state enable
commit stay
EOF
}

# Client-facing links — short outage, clear linkDown/linkUp + syslog.
flap_iface leaf1 ethernet-1/1
flap_iface leaf2 ethernet-1/1

if [[ "${DO_BGP}" == "1" ]]; then
  # Soft-ish event: disable then re-enable leaf1 underlay peer toward spine
  # (interface ethernet-1/49). Generates BGP + interface syslog/traps.
  info "Bounce leaf1 ethernet-1/49 (spine uplink) for ${FLAP_SECS}s..."
  docker exec -i leaf1 bash -c "sr_cli -ed" <<EOF
set / interface ethernet-1/49 admin-state disable
commit stay
EOF
  sleep "${FLAP_SECS}"
  docker exec -i leaf1 bash -c "sr_cli -ed" <<EOF
set / interface ethernet-1/49 admin-state enable
commit stay
EOF
fi

info "Events emitted. Wait ~30–60s then check:"
info "  docker logs --since 2m \$(docker ps -qf name=ktranslate_snmp_srl) | grep -i trap"
info "  LogQL traps:  {service_name=\"ktranslate\"} |= \`\"eventType\":\"KSnmpTrap\"\` | json | device_name =~ \".+\""
info "  LogQL syslog: {service_name=\"ktranslate\"} |= \`\"tags.container_service\":\"syslog\"\` | json | device_name =~ \"leaf|spine\""
