#!/usr/bin/env bash
# Stop NetBox OSS sidecar (keeps volumes unless NETBOX_OSS_PURGE=1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STACK="${ROOT}/netbox-oss/netbox-docker"
PORT="${NETBOX_OSS_PORT:-8000}"

[[ -d "$STACK" ]] || { echo "No ${STACK} — nothing to stop"; exit 0; }

if [[ "${NETBOX_OSS_PURGE:-0}" == "1" ]]; then
  echo "==> docker compose down -v (purge volumes)"
  ( cd "$STACK" && NETBOX_OSS_PORT="$PORT" docker compose down -v )
else
  echo "==> docker compose down (volumes kept)"
  ( cd "$STACK" && NETBOX_OSS_PORT="$PORT" docker compose down )
fi
