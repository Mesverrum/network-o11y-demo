#!/usr/bin/env bash
# update-snmp-targets.sh — rewrite groups/srl.env TARGETS to /32 mgmt IPs
# of spine1, leaf1, leaf2 on the ContainerLab management network, then
# regenerate discovery config so `make discover GROUP=srl` scans the right hosts.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROUP_ENV="${ROOT}/groups/srl.env"
NODES=(spine1 leaf1 leaf2)

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ -f "$GROUP_ENV" ]] || die "missing ${GROUP_ENV} — cp groups/srl.env.sample groups/srl.env"

CLAB_NET="${CLAB_NETWORK:-clab}"
docker network inspect "$CLAB_NET" >/dev/null 2>&1 \
  || die "docker network ${CLAB_NET} not found — check CLAB_NETWORK / clab deploy"

targets=()
for node in "${NODES[@]}"; do
  ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$node" 2>/dev/null || true)"
  [[ -n "$ip" && "$ip" != "<no value>" ]] || die "could not resolve mgmt IP for ${node} on ${CLAB_NET}"
  info "${node} → ${ip}/32"
  targets+=("${ip}/32")
done

joined="$(IFS=,; echo "${targets[*]}")"

python3 - "$GROUP_ENV" "$joined" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
targets = sys.argv[2]
text = path.read_text()
new, n = re.subn(r"(?m)^TARGETS=.*$", f"TARGETS={targets}", text, count=1)
if n != 1:
    sys.exit("could not find TARGETS= in groups/srl.env")
path.write_text(new)
print(f"updated {path} TARGETS={targets}")
PY

info "Regenerating group configs..."
bash "${ROOT}/scripts/generate-groups.sh"
info "Done. Run: make discover GROUP=srl"
