#!/usr/bin/env bash
# Resolve the clab-reachable IP for a ktranslate listener (compose container or k8s hostNetwork).
#
# Colocated k3s: export KTRANSLATE_CLAB_HOST to the clab bridge gateway before post-telemetry-config.
# Compose: auto-discovers per-service container IP on CLAB_NETWORK.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"
CLAB_NET="${CLAB_NETWORK:-clab}"

service="${1:-}"
case "$service" in
  flow)   container="ktranslate_flow" ;;
  sflow)  container="ktranslate_sflow" ;;
  syslog) container="ktranslate_syslog" ;;
  snmp)
    container="$(snmp_poller_service_name "$(primary_snmp_group "${ROOT}")")"
    ;;
  *)
    echo "usage: collector-clab-ip.sh {flow|sflow|syslog|snmp}" >&2
    exit 1
    ;;
esac

if [[ -n "${KTRANSLATE_CLAB_HOST:-}" ]]; then
  echo "${KTRANSLATE_CLAB_HOST}"
  exit 0
fi

ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "${container}" 2>/dev/null || true)"
if [[ -n "$ip" && "$ip" != "<no value>" ]]; then
  echo "$ip"
  exit 0
fi

gw="$(docker network inspect "${CLAB_NET}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
if [[ -n "$gw" && "$gw" != "<no value>" ]]; then
  echo "$gw"
  exit 0
fi

echo "ERROR: cannot resolve collector IP for ${service} on ${CLAB_NET}" >&2
exit 1
