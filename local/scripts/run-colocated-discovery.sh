#!/usr/bin/env bash
# SNMP discovery on colocated k3s hosts — docker run --network host (no compose merge).
#
# Usage: ./scripts/run-colocated-discovery.sh <group>
set -euo pipefail

GROUP="${1:-}"
[[ -n "${GROUP}" ]] || { echo "usage: $0 <group>" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

export HOME="${HOME:-/root}"
export KTRANS_HOST="$(bash "${ROOT}/scripts/host-id.sh")"
export KTRANSLATE_OTEL_ENDPOINT="${KTRANSLATE_OTEL_ENDPOINT:-http://127.0.0.1:4317/}"

SRC="${ROOT}/config/discovery-${GROUP}.yaml"
RUNTIME="${ROOT}/state/discovery-${GROUP}.runtime.yaml"
IMAGE="${KTRANSLATE_IMAGE:-quay.io/kentik/ktranslate:latest}"

[[ -f "${SRC}" ]] || { echo "missing ${SRC}" >&2; exit 1; }
[[ -f "${ROOT}/.env" ]] || { echo "missing ${ROOT}/.env" >&2; exit 1; }

mkdir -p "${ROOT}/state"
cp "${SRC}" "${RUNTIME}"
chown 1000:1000 "${RUNTIME}" 2>/dev/null || true

echo "==> colocated discovery (docker host network → ${KTRANSLATE_OTEL_ENDPOINT}) group=${GROUP}"

docker run --rm --network host \
  --env-file "${ROOT}/.env" \
  --env-file "${ROOT}/compose-host.generated.env" \
  -e "OTEL_SERVICE_NAME=ktranslate-discover-${GROUP}-${KTRANS_HOST}" \
  -e "OTEL_METRIC_EXPORT_INTERVAL=10000" \
  -e "KTRANSLATE_OTEL_ENDPOINT=${KTRANSLATE_OTEL_ENDPOINT}" \
  -v "${RUNTIME}:/snmp.yaml:rw" \
  -v "${ROOT}/snmp-profiles/nokia/nokia-srlinux.yml:/etc/ktranslate/profiles/kentik_snmp/nokia/nokia-srlinux.yml:ro" \
  "${IMAGE}" \
  --format=otel \
  --format_metric=otel \
  --otel.protocol=grpc \
  --otel.endpoint="${KTRANSLATE_OTEL_ENDPOINT}" \
  --snmp=/snmp.yaml \
  -snmp_discovery=true \
  --sinks=otel \
  --metrics=jchf \
  --tee_logs=true \
  --service_name="discover-${GROUP}"
