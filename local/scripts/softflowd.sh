#!/usr/bin/env bash
# softflowd.sh — install/start softflowd on client1/client2 → ktranslate_flow:9995

set -euo pipefail

CLAB_NET="${CLAB_NETWORK:-clab}"
CLIENTS=(client1 client2)

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

kt_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" ktranslate_flow 2>/dev/null || true)"
[[ -n "$kt_ip" ]] || die "ktranslate_flow not on network ${CLAB_NET} — is compose up?"

info "NetFlow collector: ${kt_ip}:9995"

for c in "${CLIENTS[@]}"; do
  docker inspect "$c" >/dev/null 2>&1 || die "container ${c} not found"
  info "Starting softflowd on ${c}..."
  docker exec "$c" sh -c "
    which softflowd >/dev/null 2>&1 || apk add --no-cache softflowd >/dev/null 2>&1
    pkill softflowd 2>/dev/null || true
    sleep 1
    softflowd -i eth1 -n ${kt_ip}:9995 -v 9 -P udp
    pgrep softflowd >/dev/null && echo 'softflowd running' || echo 'softflowd FAILED'
  "
done

info "Done."
