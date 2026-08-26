#!/usr/bin/env bash
# workshop-inject-fault.sh — sustained Clos incident for the webinar hunt.
#
# Admin-disables HQ leaf1 ethernet-1/1 (client-facing). Students see it on
# Device Summary / Details + traps/syslog. Public-VIP synthetics stay green.
#
# Usage:
#   ./scripts/workshop-inject-fault.sh start
#   ./scripts/workshop-inject-fault.sh stop
#   ./scripts/workshop-inject-fault.sh status
#
# Override: WORKSHOP_FAULT_NODE=leaf-br1 WORKSHOP_FAULT_IFACE=ethernet-1/1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

NODE="${WORKSHOP_FAULT_NODE:-leaf1}"
IFACE="${WORKSHOP_FAULT_IFACE:-ethernet-1/1}"
cmd="${1:-status}"

ensure_node() {
  docker inspect "$NODE" >/dev/null 2>&1 || die "container ${NODE} not found"
}

sr_set() {
  local state="$1"
  printf 'set / interface %s admin-state %s\ncommit stay\n' "$IFACE" "$state" \
    | docker exec -i "$NODE" bash -c 'sr_cli -ed'
}

stop_events_loop() {
  if [[ -x "${ROOT}/scripts/events-loop.sh" ]]; then
    info "Stopping events-loop so background flaps do not compete with the hunt"
    bash "${ROOT}/scripts/events-loop.sh" stop || true
  fi
}

start() {
  ensure_node
  stop_events_loop
  info "Disabling ${NODE} ${IFACE} (sustained — students hunt this)"
  sr_set disable
  info "Wait ~90s for the 60s SNMP poll. Confirm on YOUR Device Details before pasting Lab 5."
  info "Public VIP synthetics should stay green. Clear with: make -C local workshop-fault-stop"
  status
}

stop() {
  ensure_node
  info "Re-enabling ${NODE} ${IFACE}"
  sr_set enable
  status
}

status() {
  ensure_node
  echo -n "${NODE} ${IFACE} admin-state: "
  docker exec "$NODE" bash -c "sr_cli -c 'info from running interface ${IFACE} admin-state'" \
    | tr -s '[:space:]' ' ' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    || echo "(unavailable)"
  if [[ -x "${ROOT}/scripts/events-loop.sh" ]]; then
    echo -n "events-loop: "
    bash "${ROOT}/scripts/events-loop.sh" status 2>/dev/null | head -3 || echo "(unknown)"
  fi
}

case "$cmd" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) die "usage: $0 start|stop|status" ;;
esac
