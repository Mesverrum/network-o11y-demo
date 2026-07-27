#!/usr/bin/env bash
# lab-log-status.sh — show recent lab audit + docker event logs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=lab-log.sh
source "${ROOT}/scripts/lab-log.sh"

ACTIONS="$(lab_log_actions_file)"
EVENTS="$(lab_log_events_file)"
LINES="${1:-40}"

echo "── lab-actions.log (last ${LINES}) ──"
if [[ -f "${ACTIONS}" ]]; then
  tail -n "${LINES}" "${ACTIONS}"
else
  echo "(no log yet — run any make target or script)"
fi

echo ""
echo "── docker-events.log (last ${LINES}) ──"
if [[ -f "${EVENTS}" ]]; then
  tail -n "${LINES}" "${EVENTS}"
else
  echo "(no log — run: make lab-log-events)"
fi

echo ""
bash "${ROOT}/scripts/lab-log-events.sh" status 2>/dev/null || true
