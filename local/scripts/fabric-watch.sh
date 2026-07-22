#!/usr/bin/env bash
# fabric-watch.sh — keep SRL fabric alive (recover stopped/missing nodes).
#
# Usage:
#   ./scripts/fabric-watch.sh start
#   ./scripts/fabric-watch.sh stop
#   ./scripts/fabric-watch.sh status
#
# Env:
#   FABRIC_WATCH_INTERVAL_SEC=60   poll interval
#   FABRIC_WATCH_COOLDOWN_SEC=120  min gap between recover attempts

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${ROOT}/state"
PID_FILE="${STATE_DIR}/fabric-watch.pid"
LOG_FILE="${STATE_DIR}/fabric-watch.log"
INTERVAL_SEC="${FABRIC_WATCH_INTERVAL_SEC:-60}"
COOLDOWN_SEC="${FABRIC_WATCH_COOLDOWN_SEC:-120}"

SRL=(spine1 leaf1 leaf2)

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
    info "fabric-watch not running"
    rm -f "${PID_FILE}"
    pkill -f 'fabric-watch-worker' 2>/dev/null || true
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  info "Stopping fabric-watch (pid ${pid})..."
  kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  pkill -f 'fabric-watch-worker' 2>/dev/null || true
  rm -f "${PID_FILE}"
  sleep 1
  info "Stopped"
}

status() {
  if is_running; then
    echo "fabric-watch: running (pid $(cat "${PID_FILE}"))"
    echo "  poll every ${INTERVAL_SEC}s, cooldown ${COOLDOWN_SEC}s"
    echo "  log: ${LOG_FILE}"
    tail -n 15 "${LOG_FILE}" 2>/dev/null | sed 's/^/  | /' || true
  else
    echo "fabric-watch: stopped"
    rm -f "${PID_FILE}"
  fi
}

srl_healthy() {
  local n
  for n in "${SRL[@]}"; do
    [[ "$(docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null || echo false)" == "true" ]] || return 1
  done
  return 0
}

run_supervisor() {
  local last_recover=0 now
  echo "[$(date -Is)] fabric-watch-worker start interval=${INTERVAL_SEC}s cooldown=${COOLDOWN_SEC}s"

  while true; do
    if srl_healthy; then
      sleep "${INTERVAL_SEC}"
      continue
    fi

    now=$(date +%s)
    if (( now - last_recover < COOLDOWN_SEC )); then
      echo "[$(date -Is)] SRL unhealthy but in cooldown — sleeping"
      sleep "${INTERVAL_SEC}"
      continue
    fi

    echo "[$(date -Is)] SRL unhealthy — running fabric-stabilize"
    set +e
    bash "${ROOT}/scripts/fabric-stabilize.sh"
    rc=$?
    set -e
    echo "[$(date -Is)] fabric-stabilize exit=${rc}"
    last_recover=$now
    sleep "${INTERVAL_SEC}"
  done
}

start() {
  mkdir -p "${STATE_DIR}"
  if is_running; then
    info "fabric-watch already running (pid $(cat "${PID_FILE}"))"
    status
    return 0
  fi

  info "Starting fabric-watch (poll every ${INTERVAL_SEC}s)"
  setsid nohup env \
    FABRIC_WATCH_INTERVAL_SEC="${INTERVAL_SEC}" \
    FABRIC_WATCH_COOLDOWN_SEC="${COOLDOWN_SEC}" \
    bash "${ROOT}/scripts/fabric-watch.sh" _run \
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
    echo "Usage: $0 {start|stop|status}" >&2
    exit 1
    ;;
esac
