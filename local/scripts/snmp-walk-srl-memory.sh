#!/usr/bin/env bash
# Walk Nokia memory + IF-MIB ifAlias on lab SRL nodes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAB_NET="${CLAB_NETWORK:-clab}"
COMM="${SNMP_COMMUNITY:-public}"

for node in spine1 leaf1 leaf2; do
  ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$node" 2>/dev/null || true)"
  [[ -n "$ip" && "$ip" != "<no value>" ]] || { echo "SKIP $node (no IP)"; continue; }
  echo "======== $node ($ip) ========"
  echo "-- TIMETRA-SYSTEM-MIB memory (sgi*) --"
  snmpget -v2c -c "$COMM" -On "$ip" \
    1.3.6.1.4.1.6527.3.1.2.1.1.1.0 \
    1.3.6.1.4.1.6527.3.1.2.1.1.9.0 \
    1.3.6.1.4.1.6527.3.1.2.1.1.10.0 2>/dev/null || echo "(sgi OIDs missing)"
  echo "-- HOST-RESOURCES-MIB memory --"
  snmpwalk -v2c -c "$COMM" -On "$ip" 1.3.6.1.2.1.25.2.3.1 2>/dev/null | head -8 || true
  echo "-- ifAlias sample --"
  snmpwalk -v2c -c "$COMM" -On "$ip" 1.3.6.1.2.1.31.1.1.1.18 2>/dev/null | head -12 || true
  echo
done
