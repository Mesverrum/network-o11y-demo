#!/usr/bin/env bash
# finish-bringup.sh — SNMP recovery after clab IP drift (refresh targets + discover + poller).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

for n in spine1 leaf1 leaf2; do
  docker exec "$n" sr_cli -ec 'discard stay' 2>/dev/null || true
done
sleep 5

bash "${ROOT}/scripts/update-snmp-targets.sh"
make generate
bash "${ROOT}/scripts/enable-snmp-srl.sh"
make discover GROUP=srl
bash "${ROOT}/scripts/reload-ktranslate-devices.sh"

echo ""
echo "=== snmpget after recovery ==="
for n in spine1 leaf1 leaf2; do
  ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "clab").IPAddress}}' "$n" 2>/dev/null || true)
  [[ -n "$ip" && "$ip" != "<no value>" ]] || continue
  printf "  %s (%s): " "$n" "$ip"
  snmpget -v2c -c public -t 2 -r 1 "${ip}:161" 1.3.6.1.2.1.1.5.0 2>&1 | head -1
done
