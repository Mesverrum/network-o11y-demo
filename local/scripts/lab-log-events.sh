#!/usr/bin/env bash
# lab-log-events.sh — tee docker die/kill/stop/start/restart/destroy events to state/docker-events.log
#
# Usage:
#   ./scripts/lab-log-events.sh start
#   ./scripts/lab-log-events.sh stop
#   ./scripts/lab-log-events.sh status
#
# Env:
#   LAB_LOG_EVENTS=1        auto-start from make up / staggered-up (default 1)
#   LAB_LOG_DISABLE=1       disable all lab logging

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=lab-log.sh
source "${ROOT}/scripts/lab-log.sh"

STATE_DIR="$(lab_log_dir)"
PID_FILE="${STATE_DIR}/lab-log-events.pid"
LOG_FILE="$(lab_log_events_file)"

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
    info "lab-log-events not running"
    rm -f "${PID_FILE}"
    pkill -f 'lab-log-events-worker' 2>/dev/null || true
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  info "Stopping lab-log-events (pid ${pid})..."
  kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  pkill -f 'lab-log-events-worker' 2>/dev/null || true
  rm -f "${PID_FILE}"
  lab_log_action events "stop pid=${pid}"
  info "Stopped"
}

status() {
  if is_running; then
    echo "lab-log-events: running (pid $(cat "${PID_FILE}"))"
    echo "  log: ${LOG_FILE}"
    tail -n 10 "${LOG_FILE}" 2>/dev/null | sed 's/^/  | /' || true
  else
    echo "lab-log-events: stopped"
    rm -f "${PID_FILE}"
  fi
}

run_worker() {
  echo "[$(date -Is)] lab-log-events-worker start log=${LOG_FILE}" >>"${LOG_FILE}"
  lab_log_action events "worker start log=${LOG_FILE}"
  # die/kill/stop = container exits; start/restart/create/destroy = lifecycle
  docker events \
    --filter event=die \
    --filter event=kill \
    --filter event=stop \
    --filter event=start \
    --filter event=restart \
    --filter event=destroy \
    --filter event=create \
    --format '{{.Time}} action={{.Action}} name={{.Actor.Attributes.name}} exit={{.Actor.Attributes.exitCode}} image={{.Actor.Attributes.image}}'
}

start() {
  mkdir -p "${STATE_DIR}"
  if is_running; then
    info "lab-log-events already running (pid $(cat "${PID_FILE}"))"
    status
    return 0
  fi
  info "Starting lab-log-events → ${LOG_FILE}"
  setsid nohup bash -c '
    exec bash "'"${ROOT}"'/scripts/lab-log-events.sh" _run
  ' >>"${LOG_FILE}" 2>&1 < /dev/null &
  echo $! >"${PID_FILE}"
  lab_log_action events "start pid=$(cat "${PID_FILE}")"
  sleep 1
  status
}

case "${1:-}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  _run)   run_worker ;;
  *)
    echo "Usage: $0 {start|stop|status}" >&2
    exit 1
    ;;
esac
