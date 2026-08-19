#!/usr/bin/env bash
# Generate k8s manifests for the colocated private SM probe agent.
# Requires: gcx context with SM access; probe created via synthetic-monitoring-probes-create.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE="${ROOT}/local/state"
TOKEN_FILE="${STATE}/sm-probe-colocated.token"
API_URL="synthetic-monitoring-grpc-us-east-0.grafana.net:443"
CONTEXT="${GCX_CONTEXT:-marcnetterfield1}"

[[ -f "$TOKEN_FILE" ]] || {
  echo "Missing $TOKEN_FILE — create probe first (see synthetic-monitoring-probes-create.sh)" >&2
  exit 1
}

TOKEN="$(tr -d '\r\n' <"$TOKEN_FILE")"
mkdir -p "$STATE"
gcx --context "$CONTEXT" synthetic-monitoring probes deploy \
  --probe-name sm-agent-colocated \
  --token "$TOKEN" \
  --api-server-url "$API_URL" \
  >"${STATE}/sm-agent-colocated.yaml"
echo "Wrote ${STATE}/sm-agent-colocated.yaml"
