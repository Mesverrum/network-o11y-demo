#!/usr/bin/env bash
# Shared one-click logging: tee stdout/stderr to timestamped files under <state>/logs/.
# Sourced by lab-linux.sh, common.sh (macOS/Linux bootstrap). Not meant to run directly.

oneclick_log_init() {
  local action="${1:-run}" state_dir="${2:-${HOME}/.network-o11y-demo-oneclick}"
  [[ -n "${ONECLICK_LOG_INIT:-}" ]] && return 0
  ONECLICK_LOG_INIT=1

  local log_dir="${state_dir}/logs"
  mkdir -p "$log_dir"
  ONECLICK_LOG_FILE="${ONECLICK_LOG_FILE:-${log_dir}/${action}-$(date '+%Y%m%d-%H%M%S').log}"
  printf '%s\n' "$ONECLICK_LOG_FILE" >"${log_dir}/latest.path"

  {
    printf '=== oneclick %s started %s ===\n' "$action" "$(date -Is)"
    [[ -n "${ONECLICK_LOG_CONTEXT:-}" ]] && printf '%s\n' "$ONECLICK_LOG_CONTEXT"
  } >>"$ONECLICK_LOG_FILE"

  printf 'Log: %s\n' "$ONECLICK_LOG_FILE" >&2
  exec > >(tee -a "$ONECLICK_LOG_FILE") 2>&1
}

oneclick_log_finish() {
  local label="${1:-run}" rc="${2:-0}"
  [[ -z "${ONECLICK_LOG_FILE:-}" ]] && return 0
  printf '=== oneclick %s finished %s exit=%s ===\n' "$label" "$(date -Is)" "$rc" >>"$ONECLICK_LOG_FILE"
}

# Run a command with a visible step line (output flows to the active log via tee).
run_step() {
  step "running: $*"
  "$@"
}
