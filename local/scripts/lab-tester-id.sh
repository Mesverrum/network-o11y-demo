#!/usr/bin/env bash
# Stable topology / entity tester_id for this lab (Prometheus label).
#
# Precedence:
#   1. LAB_TESTER_ID in local/.env (non-blank)
#   2. KTRANS_HOST (explicit or hostname via host-id.sh)
#   3. network-lab
#
# Used by topology-exporter labels, Alloy LLDP remap, join-app entity metrics,
# and dashboard builders. Prints the resolved value on stdout.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

v="$(grep -E '^LAB_TESTER_ID=' "${ROOT}/.env" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '\r')"
if [ -n "${v}" ]; then
  printf '%s\n' "${v}"
  exit 0
fi

host_id="$(bash "${ROOT}/scripts/host-id.sh" 2>/dev/null || true)"
if [ -n "${host_id}" ]; then
  printf '%s\n' "${host_id}"
else
  printf '%s\n' "network-lab"
fi
