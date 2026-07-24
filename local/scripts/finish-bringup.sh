#!/usr/bin/env bash
set -euo pipefail
for n in spine1 leaf1 leaf2; do
  docker exec "$n" sr_cli -ec 'discard stay' 2>/dev/null || true
done
sleep 10
for ip in 172.20.20.6 172.20.20.2 172.20.20.5; do
  echo -n "$ip: "
  snmpget -v2c -c public -t 2 "$ip:161" 1.3.6.1.2.1.1.5.0 2>&1 | head -1
done
cd /home/mnetterfield/network-o11y-demo/local
LAB_STAGGER=0 make stabilize 2>&1 | tail -20
