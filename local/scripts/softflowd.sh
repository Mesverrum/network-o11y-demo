#!/usr/bin/env bash
# softflowd.sh — install/start softflowd on clients → ktranslate_flow:9995
# Optional dual-export to Orb pktvisor (ORB_PKTVISOR=1) on host:19995
# and/or Alloy otelcol.receiver.netflow (LAB_ALLOY_NETFLOW=1) on :2055.
# When dual-exporting, spawn one softflowd per destination (not multiple -n).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh" 2>/dev/null || true
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

CLAB_NET="${CLAB_NETWORK:-clab}"
CLIENTS=("${CLIENT_NODES[@]}")
NF_PORT="${ORB_PKTVISOR_NETFLOW_PORT:-19995}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

kt_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" flow 2>/dev/null || true)"
if [[ -z "$kt_ip" || "$kt_ip" == "<no value>" ]]; then
  kt_ip="${KTRANSLATE_CLAB_HOST:-}"
fi
if [[ -z "$kt_ip" ]]; then
  kt_ip="$(docker network inspect "${CLAB_NET}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
fi
[[ -n "$kt_ip" && "$kt_ip" != "<no value>" ]] || kt_ip="172.20.20.1"

# Destinations as "ip:port" — one softflowd process per (iface, dest).
# Alpine softflowd 1.1.0 documents multiple -n + optional -l (load-balance), but in
# practice dual -n starved ktranslate :9995 once pktvisor :19995 was added (only the
# last collector received exports). Separate processes = reliable fan-out copy.
DESTS=("${kt_ip}:9995")
info "NetFlow collector: ${kt_ip}:9995"

pkt_on="${ORB_PKTVISOR:-0}"
if [[ "$pkt_on" == "1" || "$pkt_on" == "true" || -n "${PKTVISOR_CLAB_HOST:-}" ]]; then
  pkt_ip="${PKTVISOR_CLAB_HOST:-$kt_ip}"
  DESTS+=("${pkt_ip}:${NF_PORT}")
  info "pktvisor NetFlow also: ${pkt_ip}:${NF_PORT}"
fi

# Alloy-native receiver (LAB_ALLOY_NETFLOW=1). Do not steal ktranslate :9995.
# Compose: alloy clab IP :2055. Colocated k3s hostNetwork: same host as KTRANSLATE_CLAB_HOST.
alloy_nf=0
case "${LAB_ALLOY_NETFLOW:-0}" in
  1|true|TRUE|yes|YES|on|ON) alloy_nf=1 ;;
esac
if [[ "${alloy_nf}" == "1" ]]; then
  alloy_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" alloy 2>/dev/null || true)"
  if [[ -z "${alloy_ip}" || "${alloy_ip}" == "<no value>" ]]; then
    alloy_ip="${kt_ip}"
  fi
  DESTS+=("${alloy_ip}:2055")
  info "Alloy NetFlow also: ${alloy_ip}:2055"
fi

# Serialize dest list for the remote shell (space-separated host:port).
DESTS_STR="${DESTS[*]}"

for c in "${CLIENTS[@]}"; do
  docker inspect "$c" >/dev/null 2>&1 || die "container ${c} not found"
  info "Starting softflowd on ${c} (eth0 mgmt + eth1 EVPN → ${#DESTS[@]} collector(s))..."
  docker exec "$c" sh -c "
    which softflowd >/dev/null 2>&1 || apk add --no-cache softflowd >/dev/null 2>&1
    pkill softflowd 2>/dev/null || true
    sleep 1
    for i in 1 2 3 4 5 6 7 8 9 10; do
      ip link show eth1 >/dev/null 2>&1 && break
      sleep 3
    done
    ip link show eth1 >/dev/null 2>&1 || { echo 'eth1 missing — run: make fabric-up'; exit 1; }
    ip link set eth1 up 2>/dev/null || true
    ip address show dev eth1 | grep -q 'inet 172.17.' || {
      echo 'eth1 has no 172.17.x address — re-run clab deploy for this client'
      exit 1
    }
    # One process per interface × destination (Alpine softflowd: one -i, one reliable -n).
    SOFT_TO='-v 9 -P udp -t udp=30 -t expint=30 -t general=60 -t maxlife=300'
    n=0
    for dest in ${DESTS_STR}; do
      n=\$((n + 1))
      softflowd -i eth0 -n \"\$dest\" -c /var/run/softflowd-eth0-\$n.ctl -p /var/run/softflowd-eth0-\$n.pid \$SOFT_TO
      softflowd -i eth1 -n \"\$dest\" -c /var/run/softflowd-eth1-\$n.ctl -p /var/run/softflowd-eth1-\$n.pid \$SOFT_TO
    done
    pgrep -a softflowd
    [ -f /tmp/softflowd-export-loop.pid ] && kill \"\$(cat /tmp/softflowd-export-loop.pid)\" 2>/dev/null || true
    nohup sh -c 'while sleep 30; do
      for ctl in /var/run/softflowd-eth*.ctl; do
        [ -S \"\$ctl\" ] || continue
        softflowctl -c \"\$ctl\" expire-all >/dev/null 2>&1
      done
    done' >/dev/null 2>&1 &
    echo \$! >/tmp/softflowd-export-loop.pid
    echo 'softflowd export loop started'
  "
done

info "Done."
