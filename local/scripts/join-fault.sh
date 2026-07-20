#!/usr/bin/env bash
# join-fault.sh — inject EVPN-path latency/loss for the Clos join demo talk track.
#
# Applies tc netem on client eth1 (data-plane). join-app spans should lengthen
# while softflowd still shows the same 5-tuple — that's the Investigation row.
#
# Usage:
#   ./scripts/join-fault.sh start [delay] [loss]   # defaults: 200ms 1% on client1
#   ./scripts/join-fault.sh stop
#   ./scripts/join-fault.sh status
#
# Examples:
#   ./scripts/join-fault.sh start 300ms 2%
#   JOIN_FAULT_DELAY=500ms ./scripts/join-fault.sh start
#   JOIN_FAULT_CLIENTS=client1,client2 ./scripts/join-fault.sh start   # both ends

set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

IFACE=eth1
# stop/status always cover both clients so leftover dual-sided netem is cleared.
ALL_CLIENTS=(client1 client2)
# start defaults to client1 only — dual-sided doubles RTT and compounds loss.
CLIENTS_CSV="${JOIN_FAULT_CLIENTS:-client1}"
IFS=',' read -r -a START_CLIENTS <<< "${CLIENTS_CSV// /,}"

cmd="${1:-status}"
DELAY="${2:-${JOIN_FAULT_DELAY:-200ms}}"
LOSS="${3:-${JOIN_FAULT_LOSS:-1%}}"

ensure_present() {
  local c
  for c in "$@"; do
    [[ -n "$c" ]] || continue
    docker inspect "$c" >/dev/null 2>&1 || die "container ${c} not found — make up first"
  done
}

ensure_tc() {
  local c="$1"
  docker exec "$c" sh -c '
    if ! command -v tc >/dev/null 2>&1; then
      apk add --no-cache iproute2 >/dev/null
    fi
  '
}

start() {
  ensure_present "${START_CLIENTS[@]}"
  info "Injecting netem on ${IFACE}: delay=${DELAY} loss=${LOSS} (clients: ${START_CLIENTS[*]})"
  local c
  for c in "${START_CLIENTS[@]}"; do
    [[ -n "$c" ]] || continue
    ensure_tc "$c"
    docker exec "$c" sh -c "
      tc qdisc del dev ${IFACE} root 2>/dev/null || true
      tc qdisc add dev ${IFACE} root netem delay ${DELAY} loss ${LOSS}
      echo -n '${c}: '
      tc qdisc show dev ${IFACE} | head -1
    "
  done
  info "Done. Watch Tempo p95 for clos-join-demo on the join demo dashboard."
  info "Clear with: make -C local join-fault-stop"
}

stop() {
  ensure_present "${ALL_CLIENTS[@]}"
  info "Clearing netem on ${IFACE} (client1+client2)..."
  local c
  for c in "${ALL_CLIENTS[@]}"; do
    docker exec "$c" sh -c "
      tc qdisc del dev ${IFACE} root 2>/dev/null || true
      echo -n '${c}: '
      tc qdisc show dev ${IFACE} | head -1 || echo '(no qdisc / cleared)'
    " || true
  done
  info "Cleared."
}

status() {
  ensure_present "${ALL_CLIENTS[@]}"
  local c
  for c in "${ALL_CLIENTS[@]}"; do
    echo -n "${c} ${IFACE}: "
    docker exec "$c" sh -c "tc qdisc show dev ${IFACE} 2>/dev/null | head -1" \
      || echo "(unavailable)"
  done
}

case "$cmd" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) die "usage: $0 start|stop|status [delay] [loss]" ;;
esac
