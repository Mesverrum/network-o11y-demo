#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
set -a
source "${ROOT}/.env"
set +a

BASE="${GC_PROM_URL%/push}"
QUERY_BASE="${BASE}"

echo "query base: ${QUERY_BASE}"

query() {
  local q="$1"
  curl -fsS -u "${GC_PROM_USER}:${GC_OTLP_KEY}" \
    --get "${QUERY_BASE}/api/v1/query" \
    --data-urlencode "query=${q}"
}

echo "=== devices ==="
query 'count by (tester_id, device_id) (network_topology_device_info)' | python3 -m json.tool
echo "=== edges ==="
query 'count by (src_device, dst_device, tester_id) (network_topology_edge_info)' | python3 -m json.tool
