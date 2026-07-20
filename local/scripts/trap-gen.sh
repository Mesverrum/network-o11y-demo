#!/usr/bin/env bash
# trap-gen.sh — send SNMPv2c test traps to the local ktranslate SNMP poller
#
# Poller listens on UDP 1620 (groups/srl.env TRAP_PORT) with community "public".
# Host mapping: 0.0.0.0:1620 → ktranslate_snmp_srl.
# On the clab network the poller is also reachable at <container>:1620.
#
# Usage:
#   ./scripts/trap-gen.sh              # one of each common trap
#   ./scripts/trap-gen.sh linkDown
#   ./scripts/trap-gen.sh burst 20     # 20 mixed traps
#   ./scripts/trap-gen.sh loop         # every TRAPS_INTERVAL_SEC (default 180) until Ctrl-C
#   Prefer: make events-loop  (background traps + emit-events)
#
# Verify in Grafana Cloud Loki (after ~15–60s):
#   {service_name=~"ktranslate.*"} |= "trap" or |= "linkDown" or |= "coldStart"

set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "${ROOT}/.env" ]] && set -a && source "${ROOT}/.env" && set +a

GROUP_ENV="${ROOT}/groups/srl.env"
TRAP_PORT="$(awk -F= '/^TRAP_PORT=/{print $2; exit}' "${GROUP_ENV}" 2>/dev/null || echo 1620)"
TRAP_COMMUNITY="$(awk -F= '/^TRAP_COMMUNITY=/{print $2; exit}' "${GROUP_ENV}" 2>/dev/null || echo public)"
DEST_HOST="${TRAP_DEST_HOST:-127.0.0.1}"
DEST="${DEST_HOST}:${TRAP_PORT}"

command -v snmptrap >/dev/null || die "snmptrap not found (apt install snmp)"

# Prefer container IP on clab when host mapping is awkward (WSL sometimes).
resolve_dest() {
  local cid ip
  cid="$(docker ps -qf name=ktranslate_snmp_srl | head -1 || true)"
  if [[ -n "$cid" && "${TRAP_DEST_HOST:-}" == "" ]]; then
    ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NETWORK:-clab}\").IPAddress}}" "$cid" 2>/dev/null || true)"
    if [[ -n "$ip" && "$ip" != "<no value>" ]]; then
      # Still use host port by default (works from WSL/Windows host).
      # Override with TRAP_VIA=clab to send from a container on clab.
      :
    fi
  fi
  echo "${DEST}"
}

send_trap() {
  local name="$1"; shift
  info "trap ${name} → ${DEST} (community ${TRAP_COMMUNITY})"
  # Remaining args are varbinds for snmptrap.
  snmptrap -v 2c -c "${TRAP_COMMUNITY}" "${DEST}" '' "$@"
}

trap_coldStart() {
  # SNMPv2-MIB::coldStart
  send_trap coldStart 1.3.6.1.6.3.1.1.5.1
}

trap_warmStart() {
  send_trap warmStart 1.3.6.1.6.3.1.1.5.2
}

trap_linkDown() {
  local ifIndex="${1:-1}"
  # IF-MIB linkDown + ifIndex / ifAdminStatus / ifOperStatus
  send_trap "linkDown(ifIndex=${ifIndex})" \
    1.3.6.1.6.3.1.1.5.3 \
    1.3.6.1.2.1.2.2.1.1 i "${ifIndex}" \
    1.3.6.1.2.1.2.2.1.7 i 2 \
    1.3.6.1.2.1.2.2.1.8 i 2
}

trap_linkUp() {
  local ifIndex="${1:-1}"
  send_trap "linkUp(ifIndex=${ifIndex})" \
    1.3.6.1.6.3.1.1.5.4 \
    1.3.6.1.2.1.2.2.1.1 i "${ifIndex}" \
    1.3.6.1.2.1.2.2.1.7 i 1 \
    1.3.6.1.2.1.2.2.1.8 i 1
}

trap_authFail() {
  send_trap authenticationFailure 1.3.6.1.6.3.1.1.5.5
}

send_suite() {
  trap_coldStart
  trap_linkDown 49
  sleep 0.2
  trap_linkUp 49
  trap_authFail
  trap_warmStart
}

send_burst() {
  local n="${1:-10}" i
  for ((i = 1; i <= n; i++)); do
    case $((i % 4)) in
      0) trap_coldStart ;;
      1) trap_linkDown "$((i % 50 + 1))" ;;
      2) trap_linkUp "$((i % 50 + 1))" ;;
      3) trap_authFail ;;
    esac
    sleep 0.15
  done
}

DEST="$(resolve_dest)"

# Ensure poller is up
docker ps -qf name=ktranslate_snmp_srl | grep -q . \
  || die "ktranslate_snmp_srl not running — make up / check compose"

case "${1:-suite}" in
  suite|all|"")
    send_suite
    ;;
  coldStart|coldstart) trap_coldStart ;;
  warmStart|warmstart) trap_warmStart ;;
  linkDown|linkdown)   trap_linkDown "${2:-1}" ;;
  linkUp|linkup)       trap_linkUp "${2:-1}" ;;
  authFail|auth)       trap_authFail ;;
  burst)
    send_burst "${2:-10}"
    ;;
  loop)
    interval="${TRAPS_INTERVAL_SEC:-180}"
    info "looping suite every ${interval}s (Ctrl-C to stop; or use make events-loop)"
    while true; do
      send_suite
      sleep "${interval}"
    done
    ;;
  *)
    cat <<EOF
Usage: $0 [suite|coldStart|warmStart|linkDown [ifIndex]|linkUp [ifIndex]|authFail|burst [n]|loop]
  DEST=${DEST}  community=${TRAP_COMMUNITY}
  Override host with TRAP_DEST_HOST=...
EOF
    exit 1
    ;;
esac

info "Done. Check poller logs and Loki in ~30s:"
info "  docker logs --tail 50 \$(docker ps -qf name=ktranslate_snmp_srl)"
info "  LogQL: {service_name=~\"ktranslate.*\"} |~ \"(?i)trap|linkDown|coldStart|linkUp\""
