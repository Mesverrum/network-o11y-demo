#!/usr/bin/env bash
# traffic.sh — ongoing variable workloads between client1 and client2
#
# client2 ↔ client1 across the Clos (leaf2 ↔ spine1 ↔ leaf1):
#   - steady UDP ~3 Mbps (TCP stalls on this EVPN path; UDP is reliable)
#   - burst UDP ~8 Mbps for 20s, idle 40s (dashboard variability)
#   - light reverse UDP ~1 Mbps (both leaves show traffic)
#   - ICMP every 1s (always-on chatter)
#
# Usage: ./scripts/traffic.sh [start|stop|status]

set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

CLIENT1_IP=172.17.0.1
CLIENT2_IP=172.17.0.2
WORKLOAD_TAG=lab-traffic-workloads

ensure_clients() {
  for c in client1 client2; do
    docker inspect "$c" >/dev/null 2>&1 || die "container ${c} not found — deploy the lab first (make up)"
  done
}

stop_client_workloads() {
  local c="$1"
  docker exec "$c" sh -c "
    pkill -f ${WORKLOAD_TAG} 2>/dev/null || true
    pkill iperf3 2>/dev/null || true
    pkill -f 'ping -i 1 ' 2>/dev/null || true
  " >/dev/null 2>&1 || true
}

start() {
  ensure_clients

  info "Stopping any previous workloads..."
  stop_client_workloads client1
  stop_client_workloads client2
  sleep 1

  info "Starting iperf3 servers on both clients (:5201 / :5202)..."
  for c in client1 client2; do
    docker exec "$c" sh -c '
      iperf3 -s -p 5201 -D --logfile /tmp/iperf3_5201.log
      iperf3 -s -p 5202 -D --logfile /tmp/iperf3_5202.log
      echo ok
    ' | sed "s/^/  $c: /"
  done

  info "Starting ongoing variable workloads..."
  # UDP + small datagrams (-l 1200) avoid the TCP stall seen on this Clos.
  docker exec client2 sh -c "cat > /tmp/${WORKLOAD_TAG}.sh << 'SCRIPT'
#!/bin/sh
# ${WORKLOAD_TAG} — managed by local/scripts/traffic.sh
C1=${CLIENT1_IP}

# Steady UDP ~3 Mbps toward client1.
( while true; do
    iperf3 -c \"\$C1\" -p 5201 -u -b 3M -t 120 -l 1200 --logfile /tmp/iperf3_steady.log 2>/dev/null || true
    sleep 2
  done ) &

# Bursty UDP ~8 Mbps / 20s on, 40s idle.
( while true; do
    iperf3 -c \"\$C1\" -p 5202 -u -b 8M -t 20 -l 1200 --logfile /tmp/iperf3_burst.log 2>/dev/null || true
    sleep 40
  done ) &

# Light ICMP chatter.
( ping -i 1 \"\$C1\" >/tmp/ping_chatter.log 2>&1 ) &

wait
SCRIPT
chmod +x /tmp/${WORKLOAD_TAG}.sh
nohup /tmp/${WORKLOAD_TAG}.sh >/tmp/${WORKLOAD_TAG}.log 2>&1 &
echo \"client2 workloads started (PID \$!)\"
"

  # Reverse light stream so leaf1→leaf2 path is also busy.
  docker exec client1 sh -c "cat > /tmp/${WORKLOAD_TAG}.sh << 'SCRIPT'
#!/bin/sh
# ${WORKLOAD_TAG} — managed by local/scripts/traffic.sh
C2=${CLIENT2_IP}

( while true; do
    iperf3 -c \"\$C2\" -p 5201 -u -b 1M -t 120 -l 1200 --logfile /tmp/iperf3_reverse.log 2>/dev/null || true
    sleep 2
  done ) &

wait
SCRIPT
chmod +x /tmp/${WORKLOAD_TAG}.sh
nohup /tmp/${WORKLOAD_TAG}.sh >/tmp/${WORKLOAD_TAG}.log 2>&1 &
echo \"client1 reverse workload started (PID \$!)\"
"

  info "Traffic started:"
  info "  client2→client1: steady UDP 3M + burst UDP 8M/20s + ping 1/s"
  info "  client1→client2: reverse UDP 1M"
  info "Stop: make traffic-stop   Status: make traffic-status"
}

stop() {
  ensure_clients
  info "Stopping workloads..."
  for c in client1 client2; do
    stop_client_workloads "$c"
    echo "  $c: stopped"
  done
  info "Traffic stopped."
}

status() {
  ensure_clients
  info "iperf3 / workload processes:"
  for c in client1 client2; do
    iperf_n="$(docker exec "$c" sh -c 'pgrep -c iperf3 2>/dev/null || echo 0' 2>/dev/null || echo 0)"
    wl_n="$(docker exec "$c" sh -c "pgrep -cf ${WORKLOAD_TAG} 2>/dev/null || echo 0" 2>/dev/null || echo 0)"
    echo "  $c: iperf3=${iperf_n}  workload=${wl_n}"
  done
  info "Reachability (client2 → client1):"
  docker exec client2 ping -c 2 -W 2 "$CLIENT1_IP" || true
  info "Recent log tails:"
  docker exec client2 sh -c '
    echo "  --- steady (client2) ---"
    tail -n 2 /tmp/iperf3_steady.log 2>/dev/null || echo "  (none yet)"
    echo "  --- burst (client2) ---"
    tail -n 2 /tmp/iperf3_burst.log 2>/dev/null || echo "  (none yet)"
  ' || true
  docker exec client1 sh -c '
    echo "  --- reverse (client1) ---"
    tail -n 2 /tmp/iperf3_reverse.log 2>/dev/null || echo "  (none yet)"
  ' || true
}

case "${1:-start}" in
  start)  start  ;;
  stop)   stop   ;;
  status) status ;;
  *)      echo "Usage: $0 [start|stop|status]"; exit 1 ;;
esac
