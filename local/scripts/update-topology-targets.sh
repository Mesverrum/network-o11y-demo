#!/usr/bin/env bash
# update-topology-targets.sh — rewrite topology-exporter/config.yaml target hosts
# from live ContainerLab mgmt IPs (spine1, leaf1, leaf2) and sync tester_id.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG="${ROOT}/topology-exporter/config.yaml"
ALLOY="${ROOT}/alloy/config.alloy"
NODES=(spine1 leaf1 leaf2)
TESTER_ID="$(bash "${ROOT}/scripts/lab-tester-id.sh")"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ -f "$CFG" ]] || die "missing ${CFG}"

CLAB_NET="${CLAB_NETWORK:-clab}"
docker network inspect "$CLAB_NET" >/dev/null 2>&1 \
  || die "docker network ${CLAB_NET} not found — check CLAB_NETWORK / clab deploy"

declare -A IPS=()
for node in "${NODES[@]}"; do
  ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$node" 2>/dev/null || true)"
  [[ -n "$ip" && "$ip" != "<no value>" ]] || die "could not resolve mgmt IP for ${node} on ${CLAB_NET}"
  info "${node} → ${ip}"
  IPS["$node"]="$ip"
done

python3 - "$CFG" "${IPS[spine1]}" "${IPS[leaf1]}" "${IPS[leaf2]}" "$TESTER_ID" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
spine, leaf1, leaf2, tester = sys.argv[2:6]
text = path.read_text()
out = []
hosts = [spine, leaf1, leaf2]
hi = 0
for line in text.splitlines(keepends=True):
    stripped = line.lstrip()
    if hi < len(hosts) and stripped.startswith("- host:"):
        indent = line[: len(line) - len(stripped)]
        out.append(f"{indent}- host: {hosts[hi]}\n")
        hi += 1
        continue
    if "tester_id:" in line:
        indent = line[: len(line) - len(stripped)]
        out.append(f"{indent}tester_id: {tester}\n")
        continue
    out.append(line)
if hi != 3:
    sys.exit(f"expected to rewrite 3 host: lines, rewrote {hi}")
path.write_text("".join(out))
print(f"updated {path} (tester_id={tester})")
PY

if [[ -f "$ALLOY" ]]; then
  perl -pi -e "s/(\\[\"tester_id\"\\], \")[^\"]+(\")/\${1}${TESTER_ID}\${2}/g" "$ALLOY"
  info "synced tester_id in alloy/config.alloy → ${TESTER_ID}"
fi

info "Restarting topology_exporter..."
docker restart topology_exporter >/dev/null 2>&1 || true
