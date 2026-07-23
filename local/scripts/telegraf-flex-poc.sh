#!/usr/bin/env bash
# Optional Telegraf Flex-style gap-fill PoC (inputs.exec → OTLP → Alloy).
#
# Usage:
#   bash scripts/telegraf-flex-poc.sh start|stop|status|build

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose --env-file "${ROOT}/.env"
  -f "${ROOT}/compose-base.yaml"
  -f "${ROOT}/compose-groups.generated.yaml"
  -f "${ROOT}/compose-limits.generated.yaml"
  -f "${ROOT}/compose-telegraf-poc.yaml")

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

build() {
  info "Building telegraf-flex-poc image..."
  "${COMPOSE[@]}" build telegraf_flex_poc
}

start() {
  docker inspect alloy >/dev/null 2>&1 || die "alloy not running — run make up first"
  build
  info "Starting telegraf_flex_poc (exec → OTLP → alloy:4317)..."
  "${COMPOSE[@]}" up -d --no-recreate telegraf_flex_poc
  info "Metrics: srl_flex_poc_ssh_up / srl_flex_poc_bgp_peers_up (collector=telegraf-flex-poc)"
}

stop() {
  info "Stopping telegraf_flex_poc..."
  "${COMPOSE[@]}" stop telegraf_flex_poc 2>/dev/null || true
  "${COMPOSE[@]}" rm -f telegraf_flex_poc 2>/dev/null || true
}

status() {
  if docker ps --format '{{.Names}}' | grep -qx telegraf_flex_poc; then
    docker ps --filter name=telegraf_flex_poc --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
    echo ""
    docker logs telegraf_flex_poc --tail 15 2>&1 || true
  else
    echo "telegraf_flex_poc: not running (make telegraf-poc)"
  fi
}

cmd="${1:-start}"
case "${cmd}" in
  build) build ;;
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) die "usage: $0 [build|start|stop|status]" ;;
esac
