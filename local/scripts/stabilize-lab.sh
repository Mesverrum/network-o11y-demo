#!/usr/bin/env bash
# Recover a running lab without clab destroy/reconfigure (avoids SIGTERM on SRL nodes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ -f groups/srl.env ]] || die "missing groups/srl.env — cp groups/srl.env.sample groups/srl.env"
[[ -f .env ]] || die "missing .env — cp .env.example .env"
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
      docker start "$n"
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
COMPOSE=(docker compose --env-file .env
  -f compose-base.yaml
  -f compose-groups.generated.yaml
  -f compose-catalog.generated.yaml
  -f compose-limits.generated.yaml)
# shellcheck disable=SC2207
COMPOSE+=($(bash "${ROOT}/scripts/lab-topology-exporter.sh" profile))
COLLECTOR_SERVICES=(alloy ktranslate_snmp_srl ktranslate_flow ktranslate_syslog gnmic)
if bash "${ROOT}/scripts/lab-topology-exporter.sh" enabled; then
  COLLECTOR_SERVICES+=(topology_exporter)
fi

if [[ "${LAB_STAGGER:-1}" == "1" ]]; then
  for svc in "${COLLECTOR_SERVICES[@]}"; do
    info "Starting ${svc}..."
    "${COMPOSE[@]}" up -d "${svc}"
    sleep "${STAGGER_SECS}"
  done
else
  "${COMPOSE[@]}" up -d
fi

if grep -q '^DISCOVERY_SOURCE=netbox' "${ROOT}/groups/srl.env" 2>/dev/null; then
  bash "${ROOT}/scripts/netbox-bootstrap.sh" || {
    info "NetBox bootstrap failed — trying mgmt-only sync"
    set -a && . "${ROOT}/.env" && set +a
    python3 "${ROOT}/scripts/update-netbox-mgmt-ips.py" || true
  }
else
  bash "${ROOT}/scripts/update-snmp-targets.sh"
fi

bash "${ROOT}/scripts/run-discovery-all.sh" || info "discovery returned 0 devices — check SNMP + NetBox mgmt IPs"
bash "${ROOT}/scripts/lab-topology-exporter.sh" post-config
bash "${ROOT}/scripts/softflowd.sh"
bash "${ROOT}/scripts/sflow-config.sh" || info "sflow config skipped"
bash "${ROOT}/scripts/syslog-config.sh" || info "syslog config skipped"
bash "${ROOT}/scripts/snmp-trap-config.sh" || info "trap config skipped"

info "Lab stabilized. Run: make traffic && make status"
