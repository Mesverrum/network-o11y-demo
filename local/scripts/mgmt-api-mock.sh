#!/usr/bin/env bash
# Export SR Linux management API catalog + mock fixture samples over OTLP.
# APIs not enabled in the lab (NETCONF, JSON-RPC, gNOI, gRIBI) still appear
# with mock=true — see fixtures/srl-mgmt-api-catalog.json.
#
# Usage:
#   bash scripts/mgmt-api-mock.sh          # one-shot export
#   bash scripts/mgmt-api-mock.sh build

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${ROOT}/mgmt-api-mock"
BIN="${APP_DIR}/mgmt-api-mock"
OTLP="${OTEL_EXPORTER_OTLP_ENDPOINT:-localhost:4317}"
TESTER_ID="$(bash "${ROOT}/scripts/lab-tester-id.sh")"
CLAB_NET="${CLAB_NETWORK:-clab}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

build() {
  command -v go >/dev/null || die "go not found"
  info "Building mgmt-api-mock..."
  cd "${APP_DIR}"
  go mod tidy
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o mgmt-api-mock .
  info "Built ${BIN}"
}

resolve_devices() {
  local nodes=(spine1 leaf1 leaf2)
  local parts=()
  local n ip
  for n in "${nodes[@]}"; do
    docker inspect "$n" >/dev/null 2>&1 || die "container ${n} not found — is the lab up?"
    ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$n" 2>/dev/null || true)"
    [[ -n "$ip" && "$ip" != "<no value>" ]] || die "no mgmt IP for ${n} on network ${CLAB_NET}"
    parts+=("${n}=${ip}")
  done
  (IFS=,; echo "${parts[*]}")
}

emit() {
  [[ -x "${BIN}" ]] || build
  local devices
  devices="$(resolve_devices)"
  info "Exporting SR Linux mgmt API catalog (tester_id=${TESTER_ID})..."
  OTEL_EXPORTER_OTLP_ENDPOINT="${OTLP}" \
  LAB_TESTER_ID="${TESTER_ID}" \
    "${BIN}" \
      --root "${ROOT}" \
      --catalog fixtures/srl-mgmt-api-catalog.json \
      --otlp "${OTLP}" \
      --tester-id "${TESTER_ID}" \
      --devices "${devices}"
}

cmd="${1:-emit}"
case "${cmd}" in
  build) build ;;
  emit|"") emit ;;
  *)
    die "usage: $0 [build|emit]"
    ;;
esac
