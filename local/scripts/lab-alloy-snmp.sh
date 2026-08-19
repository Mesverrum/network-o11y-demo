#!/usr/bin/env bash
# Optional Alloy-native SNMP poll (LAB_ALLOY_SNMP=1). ktranslate SNMP stays running.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "${ROOT}/.env")
  set +a
fi

alloy_snmp_enabled() {
  case "${LAB_ALLOY_SNMP:-0}" in
    1|true|yes|on|TRUE|YES|ON) return 0 ;;
    *) return 1 ;;
  esac
}

case "${1:-}" in
  enabled)
    alloy_snmp_enabled
    ;;
  *)
    echo "usage: $0 enabled" >&2
    exit 2
    ;;
esac
