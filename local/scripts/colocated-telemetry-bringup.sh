#!/usr/bin/env bash
# Colocated reference: k3s telemetry from local/ golden path.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { echo "$(date -Is) [colocated-telemetry] $*"; }

export HOME="${HOME:-/root}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

log "deploying ktranslate-golden to k3s"
export HOME="${HOME:-/root}"

if [[ -f "${ROOT}/../k8s/ktranslate-golden/kustomization.yaml" ]]; then
  export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
  kubectl create namespace network-lab --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n network-lab create secret generic grafana-cloud-credentials \
    --from-literal=GC_OTLP_URL="${GC_OTLP_URL}" \
    --from-literal=GC_OTLP_ACCOUNT="${GC_OTLP_ACCOUNT}" \
    --from-literal=GC_OTLP_KEY="${GC_OTLP_KEY}" \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -k "${ROOT}/../k8s/ktranslate-golden"
  kubectl -n network-lab rollout status deployment/alloy --timeout=180s
else
  bash scripts/deploy-ktranslate-golden.sh
fi

export KTRANSLATE_CLAB_HOST="$(
  docker network inspect "${CLAB_NETWORK:-clab}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true
)"
[[ -n "$KTRANSLATE_CLAB_HOST" ]] || KTRANSLATE_CLAB_HOST="172.20.20.1"
log "collector clab host=${KTRANSLATE_CLAB_HOST}"

bash scripts/post-telemetry-config.sh || log "post-telemetry-config had warnings"
make traffic || true
make status || true
log "telemetry ready"
