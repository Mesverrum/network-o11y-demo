#!/usr/bin/env bash
# Minimal SNMP when full fabric apply fails (postdeploy /mnt/c workaround).
# Also the default path from make fabric-apply (without FULL_FABRIC=1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

NODES=("${SRL_NODES[@]}")
if [[ "${1:-}" == "--node" && -n "${2:-}" ]]; then
  NODES=("$2")
fi

for n in "${NODES[@]}"; do
  echo "=== $n ==="
  printf '%s\n' \
    'enter candidate' \
    'delete /system snmp access-group SNMPv2-RO-Community' \
    '/system snmp network-instance mgmt admin-state enable' \
    '/system snmp access-group ag1 admin-state enable' \
    '/system snmp access-group ag1 security-level no-auth-no-priv' \
    'delete /system snmp access-group ag1 community-entry ce1' \
    '/system snmp access-group ag1 community-entry ce1 community public' \
    'commit now' | docker exec -i "$n" sr_cli
done
