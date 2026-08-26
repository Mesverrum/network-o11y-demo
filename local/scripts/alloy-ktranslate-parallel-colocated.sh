#!/usr/bin/env bash
# Restore ktranslate on colocated k3s while keeping the Alloy network fork.
#
# ktranslate owns traps :1620 and syslog :1514 (classic dashboards / learners).
# Alloy fork keeps SNMP scrape + NetFlow :2055 / sFlow :6344 (no port clash).
# remotecfg is turned off so Fleet cannot re-bind 1620/1514.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "${ROOT}/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
export COLLECTOR_RUNTIME=k3s
export LAB_FABRIC_PROFILE=colocated
export HOME="${HOME:-/root}"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "${ROOT}/.env")
  set +a
fi

info() { echo "==> [ktranslate-parallel] $*"; }

upsert_env() {
  local key="$1" val="$2" file="${ROOT}/.env"
  [[ -f "${file}" ]] || { echo "ERROR: missing ${file}" >&2; exit 1; }
  if grep -qE "^${key}=" "${file}"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "${file}"
  else
    printf '\n%s=%s\n' "${key}" "${val}" >> "${file}"
  fi
}

# Parallel contract (do not steal ktranslate trap/syslog ports).
upsert_env LAB_KTRANSLATE 1
upsert_env LAB_ALLOY_SNMP 1
upsert_env LAB_ALLOY_NETFLOW 1
upsert_env LAB_ALLOY_SNMPTRAP 0
upsert_env LAB_ALLOY_SYSLOG 0
upsert_env LAB_ALLOY_FLEET 0
upsert_env LAB_ALLOY_FLEET_SNMP 0
upsert_env LAB_ALLOY_FLEET_EVENTS 0
upsert_env LAB_ALLOY_FLEET_NETFLOW 0
upsert_env LAB_ALLOY_FLEET_DISCOVERY 0

export LAB_KTRANSLATE=1
export LAB_ALLOY_SNMP=1
export LAB_ALLOY_NETFLOW=1
export LAB_ALLOY_SNMPTRAP=0
export LAB_ALLOY_SYSLOG=0
export LAB_ALLOY_FLEET=0
export LAB_ALLOY_FLEET_SNMP=0
export LAB_ALLOY_FLEET_EVENTS=0
export LAB_ALLOY_FLEET_NETFLOW=0
export LAB_ALLOY_FLEET_DISCOVERY=0

mkdir -p "${ROOT}/alloy"
[[ -f "${ROOT}/alloy/snmp-overrides.yml" ]] || echo 'overrides: []' > "${ROOT}/alloy/snmp-overrides.yml"
[[ -f "${ROOT}/alloy/snmp-targets.yml" ]] || echo '[]' > "${ROOT}/alloy/snmp-targets.yml"
[[ -f "${ROOT}/alloy/snmp-targets-cold.yml" ]] || echo '[]' > "${ROOT}/alloy/snmp-targets-cold.yml"

info "regenerating Alloy ConfigMap (no trap/syslog listeners) + ktranslate replicas=1"
cd "${ROOT}"
python3 scripts/generate-k8s-telemetry.py
if [[ -z "${SNMP_AUTHS:-}" ]]; then
  SNMP_AUTHS=$'auths:\n  public_v2:\n    version: 2\n    community: '"${SNMP_COMMUNITY:-public}"$'\n'
  export SNMP_AUTHS
fi
python3 scripts/k8s-merge-secret-literal.py -n network-lab grafana-cloud-credentials SNMP_AUTHS

info "applying Alloy first so it drops :1620/:1514"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/alloy-configmap.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/alloy.yaml"
kubectl -n network-lab delete pod -l app=alloy --wait=true --timeout=90s || true
kubectl -n network-lab rollout status deploy/alloy --timeout=180s

info "listeners after Alloy recycle (expect 2055/6344, not 1620/1514)"
ss -ulnp | grep -E ':1620|:1514|:2055|:6344|:9995|:6343|:4317' || true
if ss -ulnp | grep -q ':1620'; then
  echo "ERROR: UDP :1620 still bound — Alloy remotecfg or trap receiver still running" >&2
  ss -ulnp | grep ':1620' || true
  exit 1
fi
if ss -ulnp | grep -q ':1514'; then
  echo "ERROR: UDP :1514 still bound — Alloy syslog receiver still running" >&2
  ss -ulnp | grep ':1514' || true
  exit 1
fi

info "applying ktranslate Deployments (replicas=1)"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-snmp.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-flow.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-sflow.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-syslog.yaml"

# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"
while IFS= read -r dep; do
  if kubectl -n network-lab get deployment "${dep}" >/dev/null 2>&1; then
    info "rollout ${dep}"
    kubectl -n network-lab rollout status "deployment/${dep}" --timeout=180s
  fi
done < <(k8s_snmp_deployment_names "${ROOT}")
for dep in ktranslate-flow ktranslate-sflow ktranslate-syslog; do
  info "rollout ${dep}"
  kubectl -n network-lab rollout status "deployment/${dep}" --timeout=180s
done

export KTRANSLATE_CLAB_HOST
KTRANSLATE_CLAB_HOST="$(
  docker network inspect "${CLAB_NETWORK:-clab}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || echo 172.20.20.1
)"
info "retarget traps/syslog/sFlow/softflowd → ktranslate (${KTRANSLATE_CLAB_HOST})"
export COLLECTOR_RUNTIME=k3s
bash scripts/reload-ktranslate-devices.sh || true
bash scripts/snmp-trap-config.sh
bash scripts/syslog-config.sh
bash scripts/sflow-config.sh
bash scripts/softflowd.sh
if [[ -f scripts/alloy-snmp-discover.sh ]]; then
  bash scripts/alloy-snmp-discover.sh || true
fi
if [[ -f scripts/traffic.sh ]]; then
  bash scripts/traffic.sh || true
fi
if [[ -f scripts/emit-events.sh ]]; then
  bash scripts/emit-events.sh || true
fi

info "listeners"
ss -ulnp | grep -E ':1620|:1514|:2055|:6344|:9995|:6343|:4317' || true
info "deployments"
kubectl -n network-lab get deploy -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas
info "parallel restore done — ktranslate on 1620/1514/9995/6343; Alloy SNMP + netflow 2055/6344"
