#!/usr/bin/env bash
# update-snmp-targets.sh — sync groups/*.env TARGETS to ContainerLab mgmt IPs,
# then regenerate discovery configs (config/discovery-*.yaml cidrs list).
#
# When SITE= is set in a group file (colocated multi-group), TARGETS are scoped
# to that site's SRL nodes only. Otherwise all SRL mgmt /32s (or the mgmt /24).

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

mgmt_ip_for_node() {
  local n="$1"
  docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$n" 2>/dev/null || true
}

per_device_targets_all() {
  local ips=() n ip
  for n in "${SRL_NODES[@]}"; do
    ip="$(mgmt_ip_for_node "$n")"
    [[ -n "$ip" && "$ip" != "<no value>" ]] || continue
    ips+=("$ip")
  done
  [[ ${#ips[@]} -gt 0 ]] || return 1
  (IFS=,; echo "${ips[*]}")
}

per_device_targets_for_site() {
  local site="$1"
  local ips=() n ip ns
  for n in "${SRL_NODES[@]}"; do
    ns="$(fabric_site_for_node "$n")"
    [[ "${ns}" == "${site}" ]] || continue
    ip="$(mgmt_ip_for_node "$n")"
    [[ -n "$ip" && "$ip" != "<no value>" ]] || continue
    ips+=("$ip")
  done
  [[ ${#ips[@]} -gt 0 ]] || return 1
  (IFS=,; echo "${ips[*]}")
}

use_per_device=0
if [[ "${LAB_FABRIC_PROFILE:-}" == "colocated" ]] || [[ "${SNMP_TARGETS_MODE:-}" == "per-device" ]]; then
  use_per_device=1
fi

subnet=""
if [[ "${use_per_device}" -eq 0 ]]; then
  subnet="$(docker network inspect "$CLAB_NET" -f '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null || true)"
  if [[ -z "$subnet" || "$subnet" == "<no value>" ]]; then
    subnet="172.20.20.0/24"
    info "clab IPAM Subnet empty — using fallback ${subnet}"
  else
    info "clab mgmt subnet ${subnet}"
  fi
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

    targets=""
    if [[ "${use_per_device}" -eq 1 ]]; then
      if [[ -n "${SITE:-}" ]]; then
        targets="$(per_device_targets_for_site "${SITE}")" \
          || die "${group}: no SRL mgmt IPs for SITE=${SITE}"
        info "${group} SITE=${SITE} TARGETS: ${targets}"
      else
        targets="$(per_device_targets_all)" || die "no SRL mgmt IPs on ${CLAB_NET}"
        info "${group} TARGETS (all SRL): ${targets}"
      fi
    else
      targets="${subnet}"
      info "${group} TARGETS (subnet): ${targets}"
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
