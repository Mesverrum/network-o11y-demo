#!/usr/bin/env bash
# events-loop.sh — background periodic synthetic traps + real SRL emit-events
#
# Usage:
#   ./scripts/events-loop.sh start    # daemonize both loops
#   ./scripts/events-loop.sh stop
#   ./scripts/events-loop.sh status
#
# Intervals (seconds), overridable via env:
#   TRAPS_INTERVAL_SEC=180   # synthetic trap suite (default 3m)
#   EMIT_INTERVAL_SEC=300    # real link flaps (default 5m)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${ROOT}/state"
PID_FILE="${STATE_DIR}/events-loop.pid"
LOG_FILE="${STATE_DIR}/events-loop.log"
TRAPS_INTERVAL_SEC="${TRAPS_INTERVAL_SEC:-180}"
EMIT_INTERVAL_SEC="${EMIT_INTERVAL_SEC:-300}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

is_running() {
  [[ -f "${PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

stop() {
  if ! is_running; then
    info "events-loop not running"
    rm -f "${PID_FILE}"
    pkill -f 'events-loop-worker' 2>/dev/null || true
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  info "Stopping events-loop (pid ${pid})..."
  # Kill process group started by setsid
  kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  pkill -f 'events-loop-worker' 2>/dev/null || true
  rm -f "${PID_FILE}"
  sleep 1
  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 -- "-${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
  fi
  info "Stopped"
}

status() {
  if is_running; then
    echo "events-loop: running (pid $(cat "${PID_FILE}"))"
    echo "  traps every ${TRAPS_INTERVAL_SEC}s, emit-events every ${EMIT_INTERVAL_SEC}s"
    echo "  log: ${LOG_FILE}"
    tail -n 12 "${LOG_FILE}" 2>/dev/null | sed 's/^/  | /' || true
  else
    echo "events-loop: stopped"
    rm -f "${PID_FILE}"
  fi
}

# Long-lived supervisor (invoked under setsid/nohup as `_run`).
run_supervisor() {
  echo "[$(date -Is)] events-loop-worker start traps=${TRAPS_INTERVAL_SEC}s emit=${EMIT_INTERVAL_SEC}s"

  # Initial config + one flap cycle (best-effort; do not exit on failure)
  set +e
  ENSURE_CONFIG=1 bash "${ROOT}/scripts/emit-events.sh"
  echo "[$(date -Is)] initial emit-events exit=$?"

  (
    exec -a events-loop-worker-traps bash -c '
      ROOT="$1"; INTERVAL="$2"
      while true; do
        echo "[$(date -Is)] trap suite"
        bash "${ROOT}/scripts/trap-gen.sh" suite || echo "[$(date -Is)] WARN: trap suite failed"
        sleep "${INTERVAL}"
      done
    ' _ "${ROOT}" "${TRAPS_INTERVAL_SEC}"
  ) &

  (
    exec -a events-loop-worker-emit bash -c '
      ROOT="$1"; INTERVAL="$2"
      sleep $(( INTERVAL / 2 ))
      while true; do
        echo "[$(date -Is)] emit-events"
        ENSURE_CONFIG=0 bash "${ROOT}/scripts/emit-events.sh" || echo "[$(date -Is)] WARN: emit-events failed"
        sleep "${INTERVAL}"
      done
    ' _ "${ROOT}" "${EMIT_INTERVAL_SEC}"
  ) &

  wait
}

start() {
  mkdir -p "${STATE_DIR}"
  if is_running; then
    info "events-loop already running (pid $(cat "${PID_FILE}")) — restarting"
    stop
    sleep 1
  fi

  docker ps -qf name=ktranslate_snmp_srl | grep -q . \
    || die "ktranslate_snmp_srl not running — make up first"

  info "Starting events-loop (traps every ${TRAPS_INTERVAL_SEC}s, emit every ${EMIT_INTERVAL_SEC}s)"
  # New session + nohup so exiting make/wsl does not SIGHUP the loops.
  setsid nohup env \
    TRAPS_INTERVAL_SEC="${TRAPS_INTERVAL_SEC}" \
    EMIT_INTERVAL_SEC="${EMIT_INTERVAL_SEC}" \
    bash "${ROOT}/scripts/events-loop.sh" _run \
    >>"${LOG_FILE}" 2>&1 < /dev/null &
  echo $! >"${PID_FILE}"
  sleep 2
  status
}

case "${1:-}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  _run)   run_supervisor ;;
  *)
    cat <<EOF
Usage: $0 {start|stop|status}
  TRAPS_INTERVAL_SEC=${TRAPS_INTERVAL_SEC}  EMIT_INTERVAL_SEC=${EMIT_INTERVAL_SEC}
EOF
    exit 1
    ;;
esac
