#!/usr/bin/env bash
# Restore mgmt NI + SNMP (two-phase commit — mgmt must exist before snmp/grpc bind).
set -euo pipefail
NODES=(spine1 leaf1 leaf2)
if [[ "${1:-}" == "--node" && -n "${2:-}" ]]; then
  NODES=("$2")
fi
for n in "${NODES[@]}"; do
  echo "=== $n: mgmt NI ==="
  printf '%s\n' \
    'enter candidate' \
    'set / network-instance mgmt type ip-vrf' \
    'set / network-instance mgmt admin-state enable' \
    'set / network-instance mgmt interface mgmt0.0' \
    'set / network-instance mgmt protocols linux import-routes true' \
    'set / network-instance mgmt protocols linux export-routes true' \
    'set / network-instance mgmt protocols linux export-neighbors true' \
    'commit now' | docker exec -i "$n" sr_cli
  sleep 5
  echo "=== $n: SNMP ==="
  printf '%s\n' \
    'enter candidate' \
    'delete /system snmp access-group SNMPv2-RO-Community' \
    '/system snmp network-instance mgmt admin-state enable' \
    '/system snmp access-group ag1 admin-state enable' \
    '/system snmp access-group ag1 security-level no-auth-no-priv' \
    '/system snmp access-group ag1 community-entry ce1 community public' \
    'commit now' | docker exec -i "$n" sr_cli
  docker exec "$n" sr_cli -ec 'info from state system snmp network-instance mgmt' \
    | grep -E 'oper-state|error-msg' || true
done
