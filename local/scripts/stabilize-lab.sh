#!/usr/bin/env bash
# Recover a running lab without clab destroy/reconfigure (avoids SIGTERM on SRL nodes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

bash "${ROOT}/scripts/ensure-snmp-groups.sh"
[[ -f .env ]] || die "missing .env — cp .env.example .env"
if [[ "${LAB_LOG_EVENTS:-1}" == "1" ]]; then
  bash "${ROOT}/scripts/lab-log-events.sh" start || true
fi
if [[ ! -f compose-groups.generated.yaml ]]; then
  info "Running make generate (first-time / missing compose fragment)..."
  make generate
fi

SRL=(spine1 leaf1 leaf2)

wait_sr_cli() {
  local n=$1 tries="${2:-${LAB_SR_CLI_TRIES:-120}}"
  while (( tries-- > 0 )); do
    local out
    out=$(docker exec "$n" sr_cli -ec 'show version' 2>&1) || true
    if grep -qi 'yang reload' <<<"$out"; then
      sleep 3
      continue
    fi
    if grep -qE 'Hostname[[:space:]]+:[[:space:]]+<Unknown>' <<<"$out"; then
      sleep 3
      continue
    fi
    if docker exec "$n" sr_cli -ec 'show version' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  die "${n}: sr_cli not ready after ~$(( tries * 2 ))s (check yang reload / container logs)"
}

need_deploy=0
for n in "${SRL[@]}"; do
  if ! docker inspect "$n" >/dev/null 2>&1; then
    need_deploy=1
    break
  fi
done

if (( need_deploy )); then
  info "SRL containers missing — deploying topology (no --reconfigure)..."
  bash "${ROOT}/scripts/clab.sh" deploy
else
  info "Starting stopped SRL nodes (if any)..."
  for n in "${SRL[@]}"; do
    if [[ "$(docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null || echo false)" != "true" ]]; then
      lab_log_docker "start ${n} reason=stabilize"
      lab_run docker start "$n"
    fi
  done
fi

STABILIZE_WAIT_SECS="${LAB_STABILIZE_WAIT_SECS:-45}"
SR_CLI_TRIES="${LAB_SR_CLI_TRIES:-120}"

if (( STABILIZE_WAIT_SECS > 0 )); then
  info "Initial SR Linux settle (${STABILIZE_WAIT_SECS}s)..."
  sleep "${STABILIZE_WAIT_SECS}"
fi

info "Waiting for sr_cli on SRL nodes (up to ~$(( SR_CLI_TRIES * 2 ))s each)..."
for n in "${SRL[@]}"; do
  wait_sr_cli "$n" "${SR_CLI_TRIES}"
  info "${n}: sr_cli ready"
done

bash "${ROOT}/scripts/apply-fabric-config.sh"

info "Telemetry compose stack..."
STAGGER_SECS="${LAB_STAGGER_SECS:-25}"
COMPOSE=(docker compose --env-file .env --env-file compose-host.generated.env
  -f compose-base.yaml
  -f compose-groups.generated.yaml
  -f compose-catalog.generated.yaml
  -f compose-limits.generated.yaml)
# shellcheck disable=SC2207
COMPOSE+=($(bash "${ROOT}/scripts/lab-topology-exporter.sh" profile))
COLLECTOR_SERVICES=(alloy flow_dns)
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"
while IFS= read -r _snmp_svc; do
  COLLECTOR_SERVICES+=("${_snmp_svc}")
done < <(snmp_poller_compose_services "${ROOT}")
COLLECTOR_SERVICES+=(ktranslate_flow ktranslate_sflow ktranslate_syslog gnmic)
if bash "${ROOT}/scripts/lab-topology-exporter.sh" enabled; then
  COLLECTOR_SERVICES+=(topology_exporter)
fi

if [[ "${LAB_STAGGER:-1}" == "1" ]]; then
  for svc in "${COLLECTOR_SERVICES[@]}"; do
    info "Starting ${svc}..."
    lab_log_compose "up -d ${svc}"
    "${COMPOSE[@]}" up -d "${svc}"
    sleep "${STAGGER_SECS}"
  done
else
  lab_log_compose "up -d (all collectors)"
  "${COMPOSE[@]}" up -d
fi

bash "${ROOT}/scripts/sync-snmp-discovery.sh"
bash "${ROOT}/scripts/post-telemetry-config.sh"

info "Lab stabilized. Verify: make status"
