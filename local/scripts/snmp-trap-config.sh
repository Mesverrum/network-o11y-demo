#!/usr/bin/env bash
# snmp-trap-config.sh — point SR Linux SNMP traps at the trap sink(s).
# ktranslate: dest ktrans on TRAP_PORT (usually :1620).
# Alloy: dest alloy on :1620 (cutover) or :11620 (parallel with ktranslate).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Do not `set -a` + source .env here: fabric-nodes.sh loads it (CRLF-stripped).
# Nested set -a / local in a sourced file blows up on Windows checkouts.
if [[ -f "${ROOT}/.env" ]]; then
  if [[ -z "${LAB_ALLOY_SNMPTRAP:-}" ]]; then
    LAB_ALLOY_SNMPTRAP="$(awk -F= '/^LAB_ALLOY_SNMPTRAP=/{gsub(/\r/,""); print $2; exit}' "${ROOT}/.env" || true)"
    export LAB_ALLOY_SNMPTRAP
  fi
  if [[ -z "${LAB_KTRANSLATE:-}" ]]; then
    LAB_KTRANSLATE="$(awk -F= '/^LAB_KTRANSLATE=/{gsub(/\r/,""); print $2; exit}' "${ROOT}/.env" || true)"
    export LAB_KTRANSLATE
  fi
fi
# shellcheck source=collector-runtime-ready.sh
source "${ROOT}/scripts/collector-runtime-ready.sh"
# shellcheck source=alloy-events-ports.sh
source "${ROOT}/scripts/alloy-events-ports.sh"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"

export_colocated_clab_host
CLAB_NET="${CLAB_NETWORK:-clab}"
DEVICES=("${SRL_NODES[@]}")

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

use_alloy=0
if lab_flag_on "${LAB_ALLOY_SNMPTRAP:-0}"; then
  use_alloy=1
elif ! lab_ktranslate_on && collector_alloy_ready; then
  use_alloy=1
fi
use_ktrans=0
if lab_ktranslate_on && collector_snmp_ready; then
  use_ktrans=1
fi
if [[ "${use_alloy}" != "1" && "${use_ktrans}" != "1" ]]; then
  if collector_snmp_ready; then
    use_ktrans=1
  elif collector_alloy_ready; then
    use_alloy=1
  else
    die "no trap sink (ktranslate SNMP or Alloy)"
  fi
fi

kt_ip=""
if [[ "${use_ktrans}" == "1" ]]; then
  kt_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" snmp 2>/dev/null || true)"
  if [[ -z "$kt_ip" || "$kt_ip" == "<no value>" ]]; then
    first_group="$(snmp_group_names "${ROOT}" | head -1)"
    [[ -n "${first_group}" ]] || die "no groups/*.env"
    cid="$(docker ps -qf "name=ktranslate_snmp_${first_group}" | head -1 || true)"
    if [[ -n "$cid" ]]; then
      kt_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$cid" 2>/dev/null || true)"
    fi
  fi
  if [[ -z "$kt_ip" || "$kt_ip" == "<no value>" ]]; then
    kt_ip="${KTRANSLATE_CLAB_HOST:-}"
  fi
  [[ -n "$kt_ip" && "$kt_ip" != "<no value>" ]] || die "SNMP collector not on network ${CLAB_NET}"
fi

alloy_ip=""
alloy_port="$(alloy_trap_listen_port)"
if [[ "${use_alloy}" == "1" ]]; then
  alloy_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" alloy 2>/dev/null || true)"
  if [[ -z "$alloy_ip" || "$alloy_ip" == "<no value>" ]]; then
    alloy_ip="${KTRANSLATE_CLAB_HOST:-${kt_ip}}"
  fi
  [[ -n "$alloy_ip" && "$alloy_ip" != "<no value>" ]] || die "Alloy not on network ${CLAB_NET} — set LAB_ALLOY_SNMPTRAP=1"
fi

TRAP_COMMUNITY="$(awk -F= '/^TRAP_COMMUNITY=/{print $2; exit}' "${ROOT}/groups/"*.env 2>/dev/null | head -1)"
TRAP_COMMUNITY="${TRAP_COMMUNITY:-public}"

if [[ "${use_ktrans}" == "1" && "${use_alloy}" == "1" ]]; then
  info "Trap sinks: ktranslate ${kt_ip}:1620 + Alloy ${alloy_ip}:${alloy_port}"
elif [[ "${use_alloy}" == "1" ]]; then
  info "Trap sink: Alloy ${alloy_ip}:${alloy_port} (otelcol.receiver.snmptrap)"
else
  info "Trap sink: ktranslate ${kt_ip}"
fi

for d in "${DEVICES[@]}"; do
  if ! docker inspect "$d" >/dev/null 2>&1; then
    info "skip ${d} (container not running)"
    continue
  fi
  TRAP_PORT="$(snmp_trap_port_for_node "${ROOT}" "${d}")"
  site="$(fabric_site_for_node "${d}")"
  extra=""
  if [[ "${use_ktrans}" == "1" && "${use_alloy}" == "1" ]]; then
    extra=$(cat <<EOF
set / system snmp trap-group ktranslate destination alloy admin-state enable
set / system snmp trap-group ktranslate destination alloy address ${alloy_ip}
set / system snmp trap-group ktranslate destination alloy port ${alloy_port}
set / system snmp trap-group ktranslate destination alloy security-level no-auth-no-priv
set / system snmp trap-group ktranslate destination alloy community-entry lab-public community ${TRAP_COMMUNITY}
EOF
)
    dest_ip="${kt_ip}"
    dest_port="${TRAP_PORT}"
  elif [[ "${use_alloy}" == "1" ]]; then
    dest_ip="${alloy_ip}"
    dest_port="${alloy_port}"
  else
    dest_ip="${kt_ip}"
    dest_port="${TRAP_PORT}"
  fi
  info "Configuring SNMP traps on ${d} (site=${site}) -> ${dest_ip}:${dest_port}/udp"
  docker exec -i "$d" bash -c "sr_cli -ed" <<EOF
set / system snmp network-instance mgmt admin-state enable
set / system snmp trap-group ktranslate admin-state enable
set / system snmp trap-group ktranslate network-instance mgmt
set / system snmp trap-group ktranslate destination ktrans admin-state enable
set / system snmp trap-group ktranslate destination ktrans address ${dest_ip}
set / system snmp trap-group ktranslate destination ktrans port ${dest_port}
set / system snmp trap-group ktranslate destination ktrans security-level no-auth-no-priv
set / system snmp trap-group ktranslate destination ktrans community-entry lab-public community ${TRAP_COMMUNITY}
${extra}
commit stay
EOF
done

info "Done. installedTraps (spine1):"
docker exec spine1 cat /etc/opt/srlinux/snmp/installedTraps 2>/dev/null | head -30 || \
  echo "(file not ready yet — appears after trap-group is active)"

info "Verify: make emit-events   or   make traps (synthetic)"
