#!/usr/bin/env bash
# update-snmp-targets.sh — sync groups/*.env TARGETS to the ContainerLab mgmt CIDR,
# then regenerate discovery configs (config/discovery-*.yaml cidrs list).
#
# ktranslate discovery scans TARGETS; device IPs land in state/devices-*.yaml.
# Prefer this CIDR path over hand-editing /32 lists — IPs drift after clab redeploy.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROUPS_DIR="${ROOT}/groups"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh" 2>/dev/null || true

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

CLAB_NET="${CLAB_NETWORK:-clab}"
docker network inspect "$CLAB_NET" >/dev/null 2>&1 \
  || die "docker network ${CLAB_NET} not found — deploy fabric first (CLAB_NETWORK=${CLAB_NET})"

# Colocated (and any multi-SRL profile): use live /32 mgmt IPs — full /24 scans are
# slow on EC2 and often miss devices when SNMP is not yet enabled on all nodes.
targets=""
if [[ "${LAB_FABRIC_PROFILE:-}" == "colocated" ]] || [[ "${SNMP_TARGETS_MODE:-}" == "per-device" ]]; then
  ips=()
  for n in "${SRL_NODES[@]}"; do
    ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$n" 2>/dev/null || true)"
    [[ -n "$ip" && "$ip" != "<no value>" ]] || continue
    ips+=("$ip")
  done
  [[ ${#ips[@]} -gt 0 ]] || die "no SRL mgmt IPs on ${CLAB_NET} — is fabric up?"
  targets="$(IFS=,; echo "${ips[*]}")"
  info "per-device TARGETS (${#ips[@]} SRL nodes): ${targets}"
else
  subnet="$(docker network inspect "$CLAB_NET" -f '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null || true)"
  if [[ -z "$subnet" || "$subnet" == "<no value>" ]]; then
    subnet="172.20.20.0/24"
    info "clab IPAM Subnet empty — using fallback ${subnet}"
  else
    info "clab mgmt subnet ${subnet}"
  fi
  targets="${subnet}"
fi

shopt -s nullglob
group_files=("${GROUPS_DIR}"/*.env)
shopt -u nullglob
[[ ${#group_files[@]} -gt 0 ]] || die "no groups/*.env — cp groups/srl.env.sample groups/srl.env"

updated=0
for group_env in "${group_files[@]}"; do
  (
    # shellcheck disable=SC1090
    source "${group_env}"
    group="${GROUP:-}"
    discovery_source="${DISCOVERY_SOURCE:-cidr}"
    if [[ -z "${group}" ]]; then
      exit 0
    fi
    if [[ "${discovery_source}" == "netbox" ]]; then
      info "${group}: DISCOVERY_SOURCE=netbox — skipping TARGETS (use: make netbox-sync-mgmt)"
      exit 0
    fi
    python3 - "$group_env" "$targets" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
targets = sys.argv[2]
text = path.read_text()
if not re.search(r"(?m)^TARGETS=", text):
    sys.exit(f"no TARGETS= in {path}")
new, n = re.subn(r"(?m)^TARGETS=.*$", f"TARGETS={targets}", text, count=1)
if n != 1:
    sys.exit(f"could not update TARGETS in {path}")
if new != text:
    path.write_text(new)
    print(f"updated {path.name} TARGETS={targets}")
else:
    print(f"unchanged {path.name} TARGETS={targets}")
PY
  )
  updated=1
done

[[ "${updated}" -eq 1 ]] || die "no CIDR groups updated"

info "Regenerating group configs..."
bash "${ROOT}/scripts/generate-groups.sh"
info "Done. Run: make discover-all"
