#!/usr/bin/env bash
# Run a one-shot SNMP discovery for one credential group and publish the
# discovered device list to state/devices-${group}.yaml for the polling
# container to read via its @-include.
#
# Usage: ./scripts/run-discovery.sh <group>
#
# Exit codes (when SKIP_RELOAD=1): 0 = device list changed, 2 = unchanged, 1 = error.
#
# Colocated (k3s collectors): set COLLECTOR_RUNTIME=k3s and KTRANSLATE_OTEL_ENDPOINT
# in .env so discovery uses host network and OTLP → k3s Alloy (no compose alloy).
#
# Requires: docker, docker compose, yq (https://github.com/mikefarah/yq).

set -euo pipefail

GROUP="${1:-}"
if [[ -z "${GROUP}" ]]; then
  echo "usage: $0 <group>   (e.g. cisco, palo)" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export KTRANS_HOST="$(bash "${REPO_ROOT}/scripts/host-id.sh")"

SRC="${REPO_ROOT}/config/discovery-${GROUP}.yaml"
RUNTIME="${REPO_ROOT}/state/discovery-${GROUP}.runtime.yaml"
DEVICES_OUT="${REPO_ROOT}/state/devices-${GROUP}.yaml"
DEVICES_PREV="${REPO_ROOT}/state/devices-${GROUP}.yaml.prev"

if [[ ! -f "${SRC}" ]]; then
  echo "missing canonical discovery config: ${SRC}" >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/state"

cp "${SRC}" "${RUNTIME}"
chown 1000:1000 "${RUNTIME}" 2>/dev/null || true

if [[ -f "${DEVICES_OUT}" ]]; then
  cp "${DEVICES_OUT}" "${DEVICES_PREV}"
fi

COMPOSE_ARGS=(--env-file "${REPO_ROOT}/.env" --env-file "${REPO_ROOT}/compose-host.generated.env" -f "${REPO_ROOT}/compose-base.yaml" -f "${REPO_ROOT}/compose-groups.generated.yaml" -f "${REPO_ROOT}/compose-catalog.generated.yaml")

if [[ ! -f "${REPO_ROOT}/compose-groups.generated.yaml" ]]; then
  echo "missing generated compose file. Run ./scripts/generate-groups.sh first." >&2
  exit 1
fi
if [[ ! -f "${REPO_ROOT}/compose-catalog.generated.yaml" ]]; then
  echo "missing compose-catalog.generated.yaml. Run ./scripts/generate-groups.sh first." >&2
  exit 1
fi

if [[ "${COLLECTOR_RUNTIME:-}" == "k3s" ]]; then
  if [[ ! -f "${REPO_ROOT}/compose-colocated.generated.yaml" ]]; then
    echo "missing compose-colocated.generated.yaml. Run: make generate" >&2
    exit 1
  fi
  COMPOSE_ARGS+=(-f "${REPO_ROOT}/compose-colocated.generated.yaml")
  export KTRANSLATE_OTEL_ENDPOINT="${KTRANSLATE_OTEL_ENDPOINT:-http://127.0.0.1:4317/}"
  echo "==> colocated discovery (host network, OTLP ${KTRANSLATE_OTEL_ENDPOINT})"
fi

docker compose "${COMPOSE_ARGS[@]}" \
  --profile discovery \
  run --rm "discover_${GROUP}"

DEVICE_COUNT="$(yq '.devices | length' "${RUNTIME}")"
if [[ "${DEVICE_COUNT}" == "0" || "${DEVICE_COUNT}" == "null" ]]; then
  echo "discovery returned 0 devices for ${GROUP}; keeping previous device list" >&2
  exit 1
fi

TMP="${DEVICES_OUT}.tmp.$$"
yq '.devices' "${RUNTIME}" > "${TMP}"
chown 1000:1000 "${TMP}" 2>/dev/null || true
mv "${TMP}" "${DEVICES_OUT}"

echo "published ${DEVICE_COUNT} ${GROUP} devices to ${DEVICES_OUT}"

if [[ -f "${DEVICES_PREV}" ]] && cmp -s "${DEVICES_PREV}" "${DEVICES_OUT}"; then
  echo "device list unchanged for ${GROUP}; skipping ktranslate reload"
  exit 2
fi

if [[ -n "${SKIP_RELOAD:-}" ]]; then
  echo "device list changed for ${GROUP}; reload deferred (SKIP_RELOAD)"
  exit 0
fi

bash "${REPO_ROOT}/scripts/reload-ktranslate-devices.sh"
