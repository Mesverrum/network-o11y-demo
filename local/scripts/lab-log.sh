#!/usr/bin/env bash
# lab-log.sh — append-only audit log for lab make targets and scripts.
#
# Logs: local/state/lab-actions.log
# Optional docker event stream: local/state/docker-events.log (lab-log-events.sh)
#
# Disable: LAB_LOG_DISABLE=1
# Env (set in .env or shell): LAB_REPO_ROOT, LAB_LOG_DISABLE, LAB_LOG_EVENTS

lab_log_enabled() {
  [[ "${LAB_LOG_DISABLE:-0}" != "1" ]]
}

lab_log_root() {
  if [[ -n "${LAB_REPO_ROOT:-}" ]]; then
    echo "${LAB_REPO_ROOT}"
  else
    echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
}

lab_log_dir() {
  echo "$(lab_log_root)/state"
}

lab_log_actions_file() {
  echo "$(lab_log_dir)/lab-actions.log"
}

lab_log_events_file() {
  echo "$(lab_log_dir)/docker-events.log"
}

# lab_log_line LEVEL CATEGORY MESSAGE
lab_log_line() {
  lab_log_enabled || return 0
  local level="$1" category="$2" msg="$3"
  local dir file ts user pid ppid
  dir="$(lab_log_dir)"
  mkdir -p "$dir"
  file="$(lab_log_actions_file)"
  ts="$(date -Is 2>/dev/null || date)"
  user="${USER:-unknown}"
  pid=$$
  ppid=${PPID:-0}
  # shellcheck disable=SC2054
  printf '%s level=%s category=%s user=%s pid=%d ppid=%d %s\n' \
    "$ts" "$level" "$category" "$user" "$pid" "$ppid" "$msg" >>"$file"
}

lab_log_info()  { lab_log_line INFO  "$1" "$2"; }
lab_log_warn()  { lab_log_line WARN  "$1" "$2"; }
lab_log_error() { lab_log_line ERROR "$1" "$2"; }

# High-signal operator actions (docker, clab, compose, make, script lifecycle).
lab_log_action() {
  lab_log_line ACTION "$1" "$2"
}

lab_log_make_target() {
  local target="$1"
  lab_log_action make "target=${target} cwd=$(pwd)"
}

lab_log_script_begin() {
  local script="$1"
  shift
  lab_log_action script "begin script=${script} args=$* cwd=$(pwd)"
}

lab_log_script_end() {
  local script="$1" rc="$2"
  lab_log_action script "end script=${script} exit=${rc}"
}

lab_log_docker() {
  lab_log_action docker "$*"
}

lab_log_compose() {
  lab_log_action compose "$*"
}

lab_log_clab() {
  lab_log_action clab "$*"
}

# Run a command after logging it. Category is the log bucket (docker, compose, clab, exec).
lab_exec() {
  local category="$1"
  shift
  lab_log_action "$category" "exec: $*"
  "$@"
}

# Log + run docker / compose / containerlab when the first token matches.
lab_run() {
  if [[ $# -eq 0 ]]; then
    return 0
  fi
  case "$1" in
    docker)     lab_log_docker "$*" ;;
    compose)    lab_log_compose "$*" ;;
    containerlab|clab) lab_log_clab "$*" ;;
    *)          lab_log_action exec "$*" ;;
  esac
  "$@"
}

lab_log_trace_script() {
  [[ -n "${_LAB_LOG_TRACED:-}" ]] && return 0
  _LAB_LOG_TRACED=1
  lab_log_enabled || return 0
  local script_name="${LAB_SCRIPT_NAME:-$(basename "${BASH_SOURCE[1]:-${0}}")}"
  lab_log_script_begin "$script_name" "$@"
  # shellcheck disable=SC2064
  trap 'lab_log_script_end "'"${script_name}"'" $?' EXIT
}

# Auto-trace when sourced (not when executed directly).
if [[ "${BASH_SOURCE[0]}" != "${0}" ]] && lab_log_enabled; then
  lab_log_trace_script "$@"
fi
