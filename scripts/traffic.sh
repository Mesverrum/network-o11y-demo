#!/usr/bin/env bash
# traffic.sh — generate network traffic across the SR Linux Clos fabric
#
# Runs iperf3 flows between client pods to produce interface counters and
# sFlow data visible in ktranslate / Grafana Cloud.
#
# Usage:
#   ./scripts/traffic.sh [start|stop|status]
#
# Requirements: kubectl configured to talk to the EKS cluster
#               (either locally via SSH tunnel or on the bastion).

set -euo pipefail

NAMESPACE="network-lab"

# ─── Helpers ─────────────────────────────────────────────────────────────────

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

client_pod() {
  # Return the pod name for a given client node name
  local node="$1"
  kubectl get pod -n "$NAMESPACE" \
    -l "clabernetes/topologyNode=${node}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

# Run a command inside the actual client Docker container (nested inside launcher pod)
docker_exec() {
  local pod="$1"; local container="$2"; shift 2
  kubectl exec -n "$NAMESPACE" "$pod" -- \
    docker --host unix:///run/docker.sock exec "$container" "$@"
}

wait_for_clients() {
  info "Waiting for client pods to be ready..."
  for c in client1 client2 client3; do
    kubectl wait pod -n "$NAMESPACE" \
      -l "clabernetes/topologyNode=${c}" \
      --for=condition=Ready \
      --timeout=120s 2>/dev/null || die "Timed out waiting for $c"
  done
  info "All client pods ready."
}

# ─── Start traffic ────────────────────────────────────────────────────────────

start() {
  wait_for_clients

  C1=$(client_pod client1)
  C2=$(client_pod client2)
  C3=$(client_pod client3)

  info "Client pods:"
  echo "  client1 → $C1"
  echo "  client2 → $C2"
  echo "  client3 → $C3"

  info "Ensuring iperf3 servers are running on client1..."
  # iperf3 is launched inside the Docker container by ContainerLab exec, but re-launch defensively
  docker_exec "$C1" client1 sh -c \
    'pkill iperf3 2>/dev/null || true
     iperf3 -s -p 5201 -D --logfile /tmp/iperf3_5201.log
     iperf3 -s -p 5202 -D --logfile /tmp/iperf3_5202.log
     echo "iperf3 servers started on ports 5201/5202"' 2>&1

  info "Starting iperf3 flows from client2 → client1 (steady 10 Mbps)..."
  docker_exec "$C2" client2 sh -c \
    'pkill iperf3 2>/dev/null || true
     iperf3 -c 172.17.0.1 -p 5201 -b 10M -t 3600 --logfile /tmp/iperf3.log &
     echo "iperf3 client started (PID $!)"' 2>&1

  info "Starting iperf3 flows from client3 → client1 (bursty 10 Mbps / idle cycle)..."
  docker_exec "$C3" client3 sh -c \
    'pkill iperf3 2>/dev/null || true
     # Loop: 30s burst at 10 Mbps, 30s idle
     (while true; do
       iperf3 -c 172.17.0.1 -p 5202 -b 10M -t 30 --logfile /tmp/iperf3.log 2>&1 || true
       sleep 30
     done) &
     echo "iperf3 burst client started (PID $!)"' 2>&1

  info "Traffic generation started."
  info "Monitor with: ./scripts/traffic.sh status"
}

# ─── Stop traffic ─────────────────────────────────────────────────────────────

stop() {
  info "Stopping iperf3 on all client pods..."
  for c in client1 client2 client3; do
    POD=$(client_pod "$c")
    if [ -n "$POD" ]; then
      kubectl exec -n "$NAMESPACE" "$POD" -- \
        docker --host unix:///run/docker.sock exec "$c" \
        sh -c 'pkill iperf3 2>/dev/null && echo "stopped" || echo "nothing running"' 2>&1 \
        | sed "s/^/  $c: /"
    fi
  done
  info "Traffic stopped."
}

# ─── Status ───────────────────────────────────────────────────────────────────

status() {
  info "Client pod status:"
  kubectl get pods -n "$NAMESPACE" \
    -l "clabernetes/app=clabernetes" \
    -o custom-columns='NODE:.metadata.labels.clabernetes/topologyNode,POD:.metadata.name,STATUS:.status.phase,IP:.status.podIP' \
    | grep -E "^(client|NODE)" | sort

  echo ""
  info "iperf3 processes:"
  for c in client1 client2 client3; do
    POD=$(client_pod "$c")
    if [ -n "$POD" ]; then
      COUNT=$(kubectl exec -n "$NAMESPACE" "$POD" -- \
        docker --host unix:///run/docker.sock exec "$c" \
        sh -c 'pgrep -c iperf3 2>/dev/null || echo 0' 2>/dev/null || echo 0)
      echo "  $c ($POD): ${COUNT} iperf3 process(es)"
    else
      echo "  $c: pod not found"
    fi
  done

  echo ""
  info "SR Linux node status:"
  kubectl get pods -n "$NAMESPACE" \
    -l "clabernetes/app=clabernetes" \
    -o custom-columns='NODE:.metadata.labels.clabernetes/topologyNode,POD:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount' \
    | grep -vE "^(client|NODE)" | sort
}

# ─── Entrypoint ───────────────────────────────────────────────────────────────

case "${1:-start}" in
  start)  start  ;;
  stop)   stop   ;;
  status) status ;;
  *)      echo "Usage: $0 [start|stop|status]"; exit 1 ;;
esac
