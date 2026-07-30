#!/usr/bin/env bash
# softflowd.sh — install/start softflowd on client1/client2 → ktranslate_flow:9995

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh" 2>/dev/null || true

CLAB_NET="${CLAB_NETWORK:-clab}"
CLIENTS=(client1 client2)

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

kt_ip="$(bash "${ROOT}/scripts/collector-clab-ip.sh" flow 2>/dev/null || true)"
[[ -n "$kt_ip" ]] || die "flow collector not reachable on ${CLAB_NET} — compose up or set KTRANSLATE_CLAB_HOST"

info "NetFlow collector: ${kt_ip}:9995"

for c in "${CLIENTS[@]}"; do
  docker inspect "$c" >/dev/null 2>&1 || die "container ${c} not found"
  info "Starting softflowd on ${c} (eth0 mgmt + eth1 EVPN)..."
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
    ip address show dev eth1 | grep -q 172.17.0 || {
      echo 'eth1 has no 172.17.0.x address — re-run clab deploy for this client'
      exit 1
    }
    # Alpine softflowd 1.1.0 accepts only one -i per process — run two exporters.
  SOFT_ARGS='-v 9 -P udp -n ${kt_ip}:9995 -t udp=30 -t expint=30 -t general=60 -t maxlife=300'
    softflowd -i eth0 -c /var/run/softflowd-eth0.ctl -p /var/run/softflowd-eth0.pid \$SOFT_ARGS
    softflowd -i eth1 -c /var/run/softflowd-eth1.ctl -p /var/run/softflowd-eth1.pid \$SOFT_ARGS
    pgrep -a softflowd
    [ -f /tmp/softflowd-export-loop.pid ] && kill \"\$(cat /tmp/softflowd-export-loop.pid)\" 2>/dev/null || true
    nohup sh -c 'while sleep 30; do
      softflowctl -c /var/run/softflowd-eth0.ctl expire-all >/dev/null 2>&1
      softflowctl -c /var/run/softflowd-eth1.ctl expire-all >/dev/null 2>&1
    done' >/dev/null 2>&1 &
    echo \$! >/tmp/softflowd-export-loop.pid
    echo 'softflowd export loop started'
  "
done

info "Done."
