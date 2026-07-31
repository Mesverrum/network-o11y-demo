#!/usr/bin/env bash
# Apply generated ktranslate-golden manifests to the local kubectl context.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCAL="${ROOT}/local"
K8S="${ROOT}/k8s/ktranslate-golden"
ENV_FILE="${LOCAL}/.env"

command -v kubectl >/dev/null || { echo "ERROR: kubectl not found" >&2; exit 1; }

python3 "${LOCAL}/scripts/generate-k8s-telemetry.py"

[[ -f "$ENV_FILE" ]] || { echo "ERROR: missing ${ENV_FILE}" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source <(sed 's/\r$//' "$ENV_FILE")
set +a

for key in GC_OTLP_URL GC_OTLP_ACCOUNT GC_OTLP_KEY; do
  [[ -n "${!key:-}" ]] || { echo "ERROR: set ${key} in local/.env" >&2; exit 1; }
done

kubectl create namespace network-lab --dry-run=client -o yaml | kubectl apply -f -
kubectl -n network-lab create secret generic grafana-cloud-credentials \
  --from-literal=GC_OTLP_URL="${GC_OTLP_URL}" \
  --from-literal=GC_OTLP_ACCOUNT="${GC_OTLP_ACCOUNT}" \
  --from-literal=GC_OTLP_KEY="${GC_OTLP_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -k "${K8S}"
kubectl -n network-lab rollout status deployment/alloy --timeout=180s
# shellcheck source=snmp-group-utils.sh
source "${LOCAL}/scripts/snmp-group-utils.sh"
while IFS= read -r dep; do
  if kubectl -n network-lab get deployment "${dep}" >/dev/null 2>&1; then
    kubectl -n network-lab rollout status "deployment/${dep}" --timeout=180s
  fi
done < <(k8s_snmp_deployment_names "${LOCAL}")
for dep in ktranslate-flow ktranslate-sflow ktranslate-syslog gnmic; do
  if kubectl -n network-lab get deployment "${dep}" >/dev/null 2>&1; then
    kubectl -n network-lab rollout status "deployment/${dep}" --timeout=180s
  fi
done

export COLLECTOR_RUNTIME=k3s
if ! bash "${LOCAL}/scripts/verify-ktranslate-service-names.sh"; then
  echo "ERROR: ktranslate OTEL_SERVICE_NAME verification failed" >&2
  exit 1
fi
echo "ktranslate-golden applied (namespace=network-lab)"
