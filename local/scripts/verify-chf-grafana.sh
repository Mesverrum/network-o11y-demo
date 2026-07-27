#!/usr/bin/env bash
# Query marcnetterfield1 (or any stack in local/.env) for CHF + flow sanity checks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a && # shellcheck source=/dev/null
source "$ROOT/.env" && set +a

: "${GRAFANA_URL:?Set GRAFANA_URL in local/.env}"
: "${GRAFANA_TOKEN:?Set GRAFANA_TOKEN in local/.env}"

PROM_UID="${GRAFANA_PROM_UID:-grafanacloud-prom}"
query() {
  local q="$1"
  curl -sS -G \
    -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
    --data-urlencode "query=${q}" \
    "${GRAFANA_URL}/api/datasources/proxy/uid/${PROM_UID}/api/v1/query"
}

echo "=== CHF jchfq by service_name ==="
query 'count by (service_name) (kentik_ktranslate_chf_kkc_jchfq)' | python3 -m json.tool

echo
echo "=== SNMP traps (CHF) ==="
query 'sum(kentik_ktranslate_chf_kkc_snmp_traps)' | python3 -m json.tool

echo
echo "=== Syslog messages (CHF) ==="
query 'sum(kentik_ktranslate_chf_kkc_syslog_messages)' | python3 -m json.tool

echo
echo "=== Flow bytes series (src/dst) ==="
query 'count by (src_host, dst_host) (network_io_by_flow_bytes)' | python3 -m json.tool

echo
echo "=== All CHF series by service_name ==="
query 'count by (service_name) ({__name__=~"kentik_ktranslate_chf_kkc_.*"})' | python3 -m json.tool

echo
echo "=== Flow bytes by service_name ==="
query 'count by (service_name) (network_io_by_flow_bytes)' | python3 -m json.tool

echo
echo "=== SNMP CPU (devices) ==="
query 'count by (device_name) (kentik_snmp_CPU)' | python3 -m json.tool
