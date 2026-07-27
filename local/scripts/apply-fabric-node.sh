#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
n="${1:?usage: apply-fabric-node.sh <spine1|leaf1|leaf2>}"
cfg="${ROOT}/configs/fabric/${n}.cfg"
[[ -f "$cfg" ]] || { echo "missing $cfg" >&2; exit 1; }
docker inspect "$n" >/dev/null 2>&1 || { echo "no container $n" >&2; exit 1; }
lab_log_action fabric "apply-full node=${n} cfg=${cfg}"
{
  echo 'enter candidate'
  grep -vE '^\s*#' "$cfg" | grep -vE '^\s*$' || true
  echo 'commit stay'
} | docker exec -i "$n" sr_cli
echo "=== $n snmp mgmt oper-state ==="
docker exec "$n" sr_cli -ec 'info from state system snmp network-instance mgmt' | grep oper-state || true
