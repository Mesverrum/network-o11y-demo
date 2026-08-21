#!/usr/bin/env bash
# Apply generated ktranslate-golden manifests to the local kubectl context.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCAL="${ROOT}/local"
K8S="${ROOT}/k8s/ktranslate-golden"
ENV_FILE="${LOCAL}/.env"

command -v kubectl >/dev/null || { echo "ERROR: kubectl not found" >&2; exit 1; }

[[ -f "$ENV_FILE" ]] || { echo "ERROR: missing ${ENV_FILE}" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source <(sed 's/\r$//' "$ENV_FILE")
set +a

python3 "${LOCAL}/scripts/generate-k8s-telemetry.py"

for key in GC_OTLP_URL GC_OTLP_ACCOUNT GC_OTLP_KEY; do
  [[ -n "${!key:-}" ]] || { echo "ERROR: set ${key} in local/.env" >&2; exit 1; }
done

if [[ -z "${SNMP_AUTHS:-}" ]]; then
  SNMP_AUTHS=$'auths:\n  public_v2:\n    version: 2\n    community: '"${SNMP_COMMUNITY:-public}"$'\n'
fi

SECRET_ARGS=(
  --from-literal=GC_OTLP_URL="${GC_OTLP_URL}"
  --from-literal=GC_OTLP_ACCOUNT="${GC_OTLP_ACCOUNT}"
  --from-literal=GC_OTLP_KEY="${GC_OTLP_KEY}"
  --from-literal=SNMP_AUTHS="${SNMP_AUTHS}"
)
if [[ -n "${GC_OTLP_URL_2:-}" && -n "${GC_OTLP_ACCOUNT_2:-}" && -n "${GC_OTLP_KEY_2:-}" ]]; then
  SECRET_ARGS+=(
    --from-literal=GC_OTLP_URL_2="${GC_OTLP_URL_2}"
    --from-literal=GC_OTLP_ACCOUNT_2="${GC_OTLP_ACCOUNT_2}"
    --from-literal=GC_OTLP_KEY_2="${GC_OTLP_KEY_2}"
  )
  echo "dual OTLP: primary + GC_OTLP_*_2"
elif [[ -n "${GC_OTLP_URL_2:-}${GC_OTLP_ACCOUNT_2:-}${GC_OTLP_KEY_2:-}" ]]; then
  echo "ERROR: set all of GC_OTLP_URL_2, GC_OTLP_ACCOUNT_2, GC_OTLP_KEY_2 (or none)" >&2
  exit 1
fi

kubectl create namespace network-lab --dry-run=client -o yaml | kubectl apply -f -
kubectl -n network-lab create secret generic grafana-cloud-credentials \
  "${SECRET_ARGS[@]}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -k "${K8S}"
kubectl -n network-lab rollout status deployment/alloy --timeout=180s
kt_on=1
case "${LAB_KTRANSLATE:-1}" in
  0|false|FALSE|no|NO|off|OFF) kt_on=0 ;;
esac
# shellcheck source=snmp-group-utils.sh
source "${LOCAL}/scripts/snmp-group-utils.sh"
if [[ "${kt_on}" == "1" ]]; then
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
else
  if kubectl -n network-lab get deployment gnmic >/dev/null 2>&1; then
    kubectl -n network-lab rollout status deployment/gnmic --timeout=180s
  fi
  echo "LAB_KTRANSLATE=0 — ktranslate Deployments scaled to 0; Alloy owns SNMP/flow/traps/syslog"
fi
echo "ktranslate-golden applied (namespace=network-lab)"
