#!/usr/bin/env bash
# Optional topology_exporter — off by default to save laptop RAM.
# Enable: LAB_TOPOLOGY_EXPORTER=1 in .env and `make topology-up` (or compose --profile topology).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "${ROOT}/.env")
  set +a
fi

topology_exporter_enabled() {
  case "${LAB_TOPOLOGY_EXPORTER:-0}" in
    1|true|yes|on|TRUE|YES|ON) return 0 ;;
    *) return 1 ;;
  esac
}

case "${1:-}" in
  enabled)
    topology_exporter_enabled
    ;;
  profile)
    topology_exporter_enabled && echo --profile topology
    ;;
  post-config)
    if topology_exporter_enabled; then
      bash "${ROOT}/scripts/update-topology-targets.sh"
    else
      echo "==> topology_exporter disabled (LAB_TOPOLOGY_EXPORTER=0) — skipping topology-targets"
    fi
    ;;
  *)
    echo "usage: $0 enabled|profile|post-config" >&2
    exit 2
    ;;
esac
