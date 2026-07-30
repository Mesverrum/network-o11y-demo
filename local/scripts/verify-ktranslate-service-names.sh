#!/usr/bin/env bash
# Verify ktranslate collectors use host-suffixed OTEL service names (no bare ktranslate-flow).
#
# Checks (when applicable):
#   - compose-host.generated.env matches host-id.sh (.env KTRANS_HOST)
#   - generated k8s manifests embed the expected KTRANS_HOST
#   - running compose / k3s pod OTEL_SERVICE_NAME env
#   - live Prometheus CHF heartbeats on the operator stack (optional)
#
# Usage:
#   bash scripts/verify-ktranslate-service-names.sh
#   bash scripts/verify-ktranslate-service-names.sh --prometheus
#   COLLECTOR_RUNTIME=k3s bash scripts/verify-ktranslate-service-names.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHECK_PROM=0
for arg in "$@"; do
  case "$arg" in
    --prometheus) CHECK_PROM=1 ;;
    -h|--help)
      echo "usage: $0 [--prometheus]"
      exit 0
      ;;
  esac
done

FAIL=0
WARN=0
_ok() { printf "[ OK ]  %s\n" "$1"; }
_fail() { printf "[FAIL]  %s\n" "$1"; FAIL=$((FAIL + 1)); }
_warn() { printf "[WARN]  %s\n" "$1"; WARN=$((WARN + 1)); }

HOST_ID="$(bash "${ROOT}/scripts/host-id.sh")"
[[ -n "${HOST_ID}" ]] || { _fail "could not resolve KTRANS_HOST via host-id.sh"; exit 1; }
_ok "expected host suffix: ${HOST_ID}"

if [[ -f compose-host.generated.env ]]; then
  gen_host="$(grep -E '^KTRANS_HOST=' compose-host.generated.env | tail -n1 | cut -d= -f2- | tr -d '\r')"
  if [[ "${gen_host}" != "${HOST_ID}" ]]; then
    _fail "compose-host.generated.env has KTRANS_HOST=${gen_host:-<empty>} but host-id.sh=${HOST_ID} — run: make generate"
  else
    _ok "compose-host.generated.env matches host-id.sh"
  fi
else
  _warn "compose-host.generated.env missing — run: make generate"
fi

K8S_DIR="${ROOT}/../k8s/ktranslate-golden"
if [[ -f "${K8S_DIR}/lab-host-identity.yaml" ]]; then
  k8s_host="$(grep -E 'KTRANS_HOST:' "${K8S_DIR}/lab-host-identity.yaml" | head -n1 | sed -E 's/.*"([^"]+)".*/\1/')"
  if [[ "${k8s_host}" != "${HOST_ID}" ]]; then
    _fail "k8s/ktranslate-golden lab-host-identity has KTRANS_HOST=${k8s_host:-<empty>} — run: make generate-k8s"
  else
    _ok "k8s manifests stamped with ${HOST_ID}"
  fi
fi

_expected_suffix() {
  local base="$1"
  printf '%s-%s' "${base}" "${HOST_ID}"
}

_check_otel_name() {
  local where="$1"
  local got="$2"
  local want="$3"
  if [[ "${got}" == "${want}" ]]; then
    _ok "${where}: OTEL_SERVICE_NAME=${got}"
  elif [[ "${got}" == "${want%-*}" ]] || [[ "${got}" =~ ^ktranslate-(flow|sflow|syslog)$ ]] \
    || [[ "${got}" =~ ^ktranslate-snmp-[^-]+$ ]]; then
    _fail "${where}: unsuffixed OTEL_SERVICE_NAME=${got} (want ${want})"
  else
    _warn "${where}: OTEL_SERVICE_NAME=${got} (expected ${want})"
  fi
}

if [[ "${COLLECTOR_RUNTIME:-}" == "k3s" ]] || kubectl get namespace network-lab >/dev/null 2>&1; then
  export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
  for dep in ktranslate-flow ktranslate-sflow ktranslate-syslog ktranslate-snmp-srl; do
    if ! kubectl -n network-lab get deployment "${dep}" >/dev/null 2>&1; then
      continue
    fi
    otel="$(kubectl -n network-lab get deployment "${dep}" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="OTEL_SERVICE_NAME")].value}' 2>/dev/null || true)"
    if [[ -z "${otel}" ]]; then
      _fail "k3s deployment/${dep}: missing OTEL_SERVICE_NAME env"
      continue
    fi
    _check_otel_name "k3s/${dep}" "${otel}" "$(_expected_suffix "${dep}")"
  done
fi

if command -v docker >/dev/null 2>&1 && [[ -f compose-groups.generated.yaml ]]; then
  COMPOSE_ARGS=(
    --env-file "${ROOT}/.env"
    --env-file "${ROOT}/compose-host.generated.env"
    -f "${ROOT}/compose-base.yaml"
    -f "${ROOT}/compose-groups.generated.yaml"
    -f "${ROOT}/compose-catalog.generated.yaml"
  )
  declare -A COMPOSE_OTEL=(
    [ktranslate_flow]="$(_expected_suffix ktranslate-flow)"
    [ktranslate_sflow]="$(_expected_suffix ktranslate-sflow)"
    [ktranslate_syslog]="$(_expected_suffix ktranslate-syslog)"
  )
  for cname in "${!COMPOSE_OTEL[@]}"; do
    if ! docker ps --format '{{.Names}}' | grep -qx "${cname}"; then
      continue
    fi
    otel="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "${cname}" 2>/dev/null \
      | grep -E '^OTEL_SERVICE_NAME=' | cut -d= -f2- | tr -d '\r' || true)"
    if [[ -z "${otel}" ]]; then
      _fail "compose ${cname}: missing OTEL_SERVICE_NAME"
      continue
    fi
    _check_otel_name "compose/${cname}" "${otel}" "${COMPOSE_OTEL[${cname}]}"
  done
fi

if [[ "${CHECK_PROM}" -eq 1 ]]; then
  if [[ ! -f .env ]]; then
    _warn "no .env — skip Prometheus check"
  else
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' .env)
  set +a
  if [[ -z "${GRAFANA_URL:-}" || -z "${GRAFANA_TOKEN:-}" ]]; then
    _warn "GRAFANA_URL/GRAFANA_TOKEN unset — skip Prometheus check"
  else
    PROM_UID="${GRAFANA_PROM_UID:-grafanacloud-prom}"
    resp="$(curl -sS -G \
      -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
      --data-urlencode 'query=count by (service_name) (kentik_ktranslate_chf_kkc_jchfq)' \
      "${GRAFANA_URL}/api/datasources/proxy/uid/${PROM_UID}/api/v1/query" || true)"
    if ! echo "${resp}" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
      _warn "Prometheus query failed"
    else
      bad="$(echo "${resp}" | python3 -c "
import json, re, sys
data = json.load(sys.stdin)
bad = []
pat = re.compile(r'^ktranslate-(flow|sflow|syslog)$|^ktranslate-snmp-[^-]+\$')
for r in data.get('data', {}).get('result', []):
    sn = r.get('metric', {}).get('service_name', '')
    if pat.match(sn):
        bad.append(sn)
for sn in sorted(set(bad)):
    print(sn)
")"
      if [[ -n "${bad}" ]]; then
        while IFS= read -r line; do
          [[ -z "${line}" ]] && continue
          _fail "Prometheus CHF heartbeat with unsuffixed service_name=${line}"
        done <<< "${bad}"
      else
        names="$(echo "${resp}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(', '.join(sorted(r['metric'].get('service_name','') for r in data.get('data',{}).get('result',[]))))
")"
        _ok "Prometheus CHF service_name values: ${names:-<none>}"
      fi
    fi
  fi
  fi
fi

echo ""
if [[ "${FAIL}" -gt 0 ]]; then
  echo "FAILED: ${FAIL} check(s) failed, ${WARN} warning(s)"
  exit 1
fi
echo "All naming checks passed (${WARN} warning(s))"
exit 0
