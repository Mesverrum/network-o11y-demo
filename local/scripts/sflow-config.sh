#!/usr/bin/env bash
# sflow-config.sh — enable SR Linux sFlow on spine (and optional leaves) → ktranslate_sflow:6343
#
# Optional second collector for Orb pktvisor (ORB_PKTVISOR=1) on host:16343.
#
# Simulator note: containerized SR Linux often exports sFlow counter-samples (interface
# stats), not full flow-samples. Client softflowd (make softflowd) still provides L4 flows.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAB_NET="${CLAB_NETWORK:-clab}"
PKT_SFLOW_PORT="${ORB_PKTVISOR_SFLOW_PORT:-16343}"
# Space-separated list; default spine only.
SFLOW_DEVICES="${SFLOW_DEVICES:-spine1}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

kt_sflow=1
case "${LAB_KTRANSLATE:-1}" in
  0|false|FALSE|no|NO|off|OFF) kt_sflow=0 ;;
esac
alloy_sflow=0
case "${LAB_ALLOY_NETFLOW:-0}" in
  1|true|TRUE|yes|YES|on|ON) alloy_sflow=1 ;;
esac

gw="$(docker network inspect "${CLAB_NET}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
gw="${KTRANSLATE_CLAB_HOST:-${gw:-172.20.20.1}}"

kt_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" sflow 2>/dev/null || true)"
[[ -n "$kt_ip" && "$kt_ip" != "<no value>" ]] || kt_ip="${gw}"
alloy_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" alloy 2>/dev/null || true)"
[[ -n "$alloy_ip" && "$alloy_ip" != "<no value>" ]] || alloy_ip="${gw}"

if [[ "${kt_sflow}" == "1" ]]; then
  sflow_ip="${kt_ip}"
  SFLOW_PORT="${SFLOW_PORT:-6343}"
  info "sFlow collector 1: ktranslate ${sflow_ip}:${SFLOW_PORT}/udp"
elif [[ "${alloy_sflow}" == "1" ]]; then
  sflow_ip="${alloy_ip}"
  SFLOW_PORT="${SFLOW_PORT:-6344}"
  info "sFlow collector 1: Alloy ${sflow_ip}:${SFLOW_PORT}/udp"
else
  sflow_ip="${gw}"
  SFLOW_PORT="${SFLOW_PORT:-6343}"
  info "sFlow collector 1: ${sflow_ip}:${SFLOW_PORT}/udp"
fi

extra=""
next=2
if [[ "${kt_sflow}" == "1" && "${alloy_sflow}" == "1" ]]; then
  info "sFlow collector ${next}: Alloy ${alloy_ip}:6344/udp"
  extra+=$(cat <<PEOF

set / system sflow collector ${next} collector-address ${alloy_ip}
set / system sflow collector ${next} network-instance mgmt
set / system sflow collector ${next} source-address __SRC__
set / system sflow collector ${next} port 6344
PEOF
)
  next=$((next + 1))
fi
pkt_on="${ORB_PKTVISOR:-0}"
if [[ "$pkt_on" == "1" || "$pkt_on" == "true" || -n "${PKTVISOR_CLAB_HOST:-}" ]]; then
  pkt_ip="${PKTVISOR_CLAB_HOST:-$sflow_ip}"
  info "sFlow collector ${next}: pktvisor ${pkt_ip}:${PKT_SFLOW_PORT}/udp"
  extra+=$(cat <<PEOF

set / system sflow collector ${next} collector-address ${pkt_ip}
set / system sflow collector ${next} network-instance mgmt
set / system sflow collector ${next} source-address __SRC__
set / system sflow collector ${next} port ${PKT_SFLOW_PORT}
PEOF
)
fi

for d in ${SFLOW_DEVICES}; do
  docker inspect "$d" >/dev/null 2>&1 || die "container ${d} not found"
  src_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$d" 2>/dev/null || true)"
  [[ -n "$src_ip" && "$src_ip" != "<no value>" ]] || die "could not resolve mgmt IP for ${d} on ${CLAB_NET}"

  info "Configuring sFlow on ${d} (source ${src_ip})..."
  rendered="${extra//__SRC__/${src_ip}}"
  docker exec -i "$d" bash -c "sr_cli -ed" <<EOF
set / system sflow admin-state enable
set / system sflow sample-rate 10000
set / system sflow collector 1 collector-address ${sflow_ip}
set / system sflow collector 1 network-instance mgmt
set / system sflow collector 1 source-address ${src_ip}
set / system sflow collector 1 port ${SFLOW_PORT}
${rendered}
set / interface ethernet-1/1 sflow admin-state enable
set / interface ethernet-1/2 sflow admin-state enable
commit stay
EOF
done

info "Done. Check: docker logs ktranslate_sflow --tail 20"
