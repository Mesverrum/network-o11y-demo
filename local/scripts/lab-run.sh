#!/usr/bin/env bash
# lab-run.sh — wrap a make target invocation with audit logging.
# Usage: lab-run.sh <make-target> -- <command> [args...]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=lab-log.sh
source "${ROOT}/scripts/lab-log.sh"

target="${1:-unknown}"
shift
[[ "${1:-}" == "--" ]] && shift

lab_log_make_target "$target"

if (($# == 0)); then
  lab_log_warn make "target=${target} no command (read-only target?)"
  exit 0
fi

set +e
"$@"
rc=$?
set -e

lab_log_action make "target=${target} exit=${rc}"
exit "$rc"
