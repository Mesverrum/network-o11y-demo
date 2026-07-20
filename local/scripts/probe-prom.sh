#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
set -a
source "${ROOT}/.env"
set +a

echo "PROM_URL=${GC_PROM_URL}"
echo "USER=${GC_PROM_USER}"

for path in /api/v1/query /prometheus/api/v1/query /api/prom/api/v1/query; do
  code=$(curl -s -o /tmp/pq.json -w "%{http_code}" -u "${GC_PROM_USER}:${GC_OTLP_KEY}" \
    --get "${GC_PROM_URL}${path}" \
    --data-urlencode 'query=count(network_topology_device_info)' || true)
  echo "${path} -> ${code}"
  head -c 300 /tmp/pq.json || true
  echo
done
