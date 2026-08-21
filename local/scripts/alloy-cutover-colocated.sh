#!/usr/bin/env bash
# Scale down ktranslate on colocated k3s; Alloy remotecfg + one Fleet pipeline
# own SNMP / traps / syslog / netflow. Local ConfigMap keeps OTLP bootstrap.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "${ROOT}/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
export COLLECTOR_RUNTIME=k3s
export LAB_FABRIC_PROFILE=colocated
export LAB_ALLOY_SNMP=1
export LAB_ALLOY_NETFLOW=1
export LAB_ALLOY_SNMPTRAP=1
export LAB_ALLOY_SYSLOG=1
export LAB_ALLOY_FLEET=1
export LAB_ALLOY_FLEET_SNMP=1
export LAB_ALLOY_FLEET_EVENTS=1
export LAB_ALLOY_FLEET_NETFLOW=1
export LAB_ALLOY_FLEET_DISCOVERY="${LAB_ALLOY_FLEET_DISCOVERY:-1}"
export LAB_KTRANSLATE=0
export HOME="${HOME:-/root}"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "${ROOT}/.env")
  set +a
fi

info() { echo "==> [alloy-cutover] $*"; }

upsert_env() {
  local key="$1" val="$2" file="${ROOT}/.env"
  [[ -f "${file}" ]] || { echo "ERROR: missing ${file}" >&2; exit 1; }
  if grep -qE "^${key}=" "${file}"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "${file}"
  else
    printf '\n%s=%s\n' "${key}" "${val}" >> "${file}"
  fi
}

upsert_env LAB_ALLOY_SNMP 1
upsert_env LAB_ALLOY_NETFLOW 1
upsert_env LAB_ALLOY_SNMPTRAP 1
upsert_env LAB_ALLOY_SYSLOG 1
upsert_env LAB_ALLOY_FLEET 1
upsert_env LAB_ALLOY_FLEET_SNMP 1
upsert_env LAB_ALLOY_FLEET_EVENTS 1
upsert_env LAB_ALLOY_FLEET_NETFLOW 1
upsert_env LAB_ALLOY_FLEET_DISCOVERY "${LAB_ALLOY_FLEET_DISCOVERY}"
upsert_env LAB_KTRANSLATE 0

if [[ -z "${GC_FM_URL:-}" && -n "${GRAFANA_URL:-}" && -n "${GRAFANA_TOKEN:-}" ]]; then
  detected="$(
    curl -s -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
      "${GRAFANA_URL}/api/plugins/grafana-collector-app/settings" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("jsonData") or {}).get("agmClusterUrl") or "")' \
      2>/dev/null || true
  )"
  if [[ -n "${detected}" ]]; then
    GC_FM_URL="${detected}"
    info "detected GC_FM_URL=${GC_FM_URL}"
  fi
fi
if [[ -z "${GC_FM_URL:-}" ]]; then
  echo "ERROR: set GC_FM_URL (Fleet Management remotecfg base URL) in local/.env" >&2
  exit 1
fi
export GC_FM_URL
upsert_env GC_FM_URL "${GC_FM_URL}"
export GC_FM_TOKEN="${GC_FM_TOKEN:-${GC_OTLP_KEY:-}}"
export GC_FM_USER="${GC_FM_USER:-${GC_OTLP_ACCOUNT:-}}"

mkdir -p "${ROOT}/alloy"
[[ -f "${ROOT}/alloy/snmp-overrides.yml" ]] || echo 'overrides: []' > "${ROOT}/alloy/snmp-overrides.yml"
[[ -f "${ROOT}/alloy/snmp-targets.yml" ]] || echo '[]' > "${ROOT}/alloy/snmp-targets.yml"
[[ -f "${ROOT}/alloy/snmp-targets-cold.yml" ]] || echo '[]' > "${ROOT}/alloy/snmp-targets-cold.yml"

info "upserting Fleet pipeline network_o11y_alloy (SNMP + events + netflow)"
if python3 "${ROOT}/scripts/fleet-upsert-snmp-pipeline.py"; then
  info "Fleet pipeline upserted"
else
  echo "WARN: Fleet pipeline upsert failed (need fleet-management:write)." >&2
  echo "WARN: remotecfg will still enroll; create network.pipeline.alloy in the UI." >&2
fi

info "scaling ktranslate Deployments to 0 (free hostNetwork ports)"
kubectl -n network-lab get deploy -o name | grep -E 'ktranslate-' | while read -r dep; do
  info "scale ${dep}"
  kubectl -n network-lab scale "${dep}" --replicas=0 || true
done
sleep 4

info "regenerating Alloy + ktranslate-golden (replicas=0)"
cd "${ROOT}"
python3 scripts/generate-k8s-telemetry.py
if [[ -z "${SNMP_AUTHS:-}" ]]; then
  SNMP_AUTHS=$'auths:\n  public_v2:\n    version: 2\n    community: '"${SNMP_COMMUNITY:-public}"$'\n'
  export SNMP_AUTHS
fi
python3 scripts/k8s-merge-secret-literal.py -n network-lab grafana-cloud-credentials SNMP_AUTHS
kubectl apply -f "${REPO}/k8s/ktranslate-golden/alloy-configmap.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/alloy.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-snmp.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-flow.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-sflow.yaml"
kubectl apply -f "${REPO}/k8s/ktranslate-golden/ktranslate-syslog.yaml"
info "recycle Alloy so it can bind 1620/1514/2055/6344"
kubectl -n network-lab delete pod -l app=alloy --wait=true --timeout=90s || true
kubectl -n network-lab rollout status deploy/alloy --timeout=180s

export KTRANSLATE_CLAB_HOST
KTRANSLATE_CLAB_HOST="$(
  docker network inspect "${CLAB_NETWORK:-clab}" -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || echo 172.20.20.1
)"
info "retarget traps/syslog/sFlow/softflowd → Alloy (${KTRANSLATE_CLAB_HOST})"
bash scripts/snmp-trap-config.sh
bash scripts/syslog-config.sh
bash scripts/sflow-config.sh
bash scripts/softflowd.sh
if [[ -f scripts/traffic.sh ]]; then
  bash scripts/traffic.sh || true
fi
if [[ -f scripts/emit-events.sh ]]; then
  bash scripts/emit-events.sh || true
fi

info "listeners"
ss -ulnp | grep -E ':1620|:1514|:2055|:6344|:9995|:6343' || true
info "deployments"
kubectl -n network-lab get deploy -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas
info "Alloy config markers (local bootstrap; network River should be Fleet stubs)"
kubectl -n network-lab get cm alloy-config -o jsonpath='{.data.config\.alloy}' \
  | grep -E 'remotecfg \{|LAB_ALLOY_FLEET_|prometheus.exporter.snmp|loki.source.snmptrap|otelcol.receiver.netflow' \
  | head -20
POD="$(kubectl -n network-lab get pod -l app=alloy -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [[ -n "${POD}" ]]; then
  info "remotecfg metrics"
  kubectl -n network-lab exec "${POD}" -- wget -qO- http://127.0.0.1:12346/metrics 2>/dev/null \
    | grep -E '^remotecfg_' | head -20 || true
fi
info "cutover done — Fleet UI: ${GRAFANA_URL:-}/a/grafana-collector-app/fleet-management"
