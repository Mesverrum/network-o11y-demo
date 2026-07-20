#!/usr/bin/env bash
# join-app.sh — build/deploy OTel Clos join demo on client1 (client) + client2 (server)
#
# Traffic: client1 eth1 172.17.0.1 → EVPN Clos → client2 eth1 172.17.0.2:8080
# Traces:  OTLP gRPC → alloy:4317 (clab mgmt) → Grafana Cloud Tempo
# Flows:   softflowd on eth1 should see the same 5-tuple (make softflowd)
#
# Usage:
#   ./scripts/join-app.sh start|stop|status|build

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${ROOT}/join-app"
BIN="${APP_DIR}/join-app"
REMOTE="/usr/local/bin/join-app"
OTLP="${OTEL_EXPORTER_OTLP_ENDPOINT:-alloy:4317}"
PEER="${JOIN_PEER:-http://172.17.0.2:8080}"
INTERVAL="${JOIN_INTERVAL:-2s}"
SERVICE="${OTEL_SERVICE_NAME:-clos-join-demo}"
TESTER_ID="$(bash "${ROOT}/scripts/lab-tester-id.sh")"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

cmd="${1:-start}"

build() {
  command -v go >/dev/null || die "go not found (build on WSL host)"
  info "Building static linux/amd64 binary..."
  cd "${APP_DIR}"
  go mod tidy
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o join-app .
  info "Built ${BIN} ($(du -h join-app | awk '{print $1}'))"
}

deploy_bin() {
  build
  for c in client1 client2; do
    docker inspect "$c" >/dev/null 2>&1 || die "container ${c} not found — is the lab up?"
    docker cp "${BIN}" "${c}:${REMOTE}"
    docker exec "$c" chmod +x "${REMOTE}"
  done
}

stop() {
  info "Stopping join-app on clients..."
  for c in client1 client2; do
    docker exec "$c" sh -c 'pkill -f /usr/local/bin/join-app 2>/dev/null || true' || true
  done
}

status() {
  for c in client1 client2; do
    if docker exec "$c" sh -c 'pgrep -af join-app' 2>/dev/null; then
      :
    else
      echo "${c}: not running"
    fi
  done
  echo "---"
  docker exec client1 sh -c "wget -qO- --timeout=2 ${PEER}/healthz 2>/dev/null && echo ' (from client1)'" \
    || echo "healthz: unreachable from client1 → ${PEER}"
}

start() {
  deploy_bin
  stop
  sleep 1

  info "Starting server on client2 (listen :8080, otlp=${OTLP}, tester_id=${TESTER_ID})..."
  docker exec -d client2 sh -c "
    OTEL_SERVICE_NAME=${SERVICE} \
    OTEL_EXPORTER_OTLP_ENDPOINT=${OTLP} \
    LAB_TESTER_ID=${TESTER_ID} \
    JOIN_ROLE=server \
    nohup ${REMOTE} -role=server -listen=:8080 -otlp=${OTLP} -service=${SERVICE} \
      >/tmp/join-app-server.log 2>&1 &
  "

  # Wait for healthz over EVPN
  info "Waiting for server over EVPN..."
  ok=0
  for i in $(seq 1 15); do
    if docker exec client1 sh -c "wget -qO- --timeout=2 ${PEER}/healthz" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 1
  done
  [[ "$ok" = 1 ]] || die "server not reachable at ${PEER}/healthz from client1"

  info "Starting client on client1 (peer=${PEER}, interval=${INTERVAL}, tester_id=${TESTER_ID})..."
  docker exec -d client1 sh -c "
    OTEL_SERVICE_NAME=${SERVICE} \
    OTEL_EXPORTER_OTLP_ENDPOINT=${OTLP} \
    LAB_TESTER_ID=${TESTER_ID} \
    JOIN_ROLE=client \
    nohup ${REMOTE} -role=client -peer=${PEER} -interval=${INTERVAL} -otlp=${OTLP} -service=${SERVICE} \
      >/tmp/join-app-client.log 2>&1 &
  "

  sleep 2
  status
  info "Done. Traces: service.name=${SERVICE}. Flows: network_peer_address=172.17.0.2 network_peer_port=8080"
  info "Logs: docker exec client1 cat /tmp/join-app-client.log"
}

case "$cmd" in
  build)  build ;;
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) die "usage: $0 start|stop|status|build" ;;
esac
