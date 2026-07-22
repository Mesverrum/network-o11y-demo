#!/usr/bin/env bash
# Minimal SNMP when full fabric apply fails (postdeploy /mnt/c workaround).
set -euo pipefail

NODES=(spine1 leaf1 leaf2)
if [[ "${1:-}" == "--node" && -n "${2:-}" ]]; then
  NODES=("$2")
fi

for n in "${NODES[@]}"; do
  echo "=== $n ==="
  printf '%s\n' \
    'enter candidate' \
    '/system snmp network-instance mgmt admin-state enable' \
    '/system snmp access-group ag1 admin-state enable' \
    '/system snmp access-group ag1 security-level no-auth-no-priv' \
    'commit now' | docker exec -i "$n" sr_cli
done
