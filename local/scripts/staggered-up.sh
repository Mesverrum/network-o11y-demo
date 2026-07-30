#!/usr/bin/env bash
# Staggered lab bring-up: fabric nodes and collectors one at a time with settle
# pauses so Docker is not hit by simultaneous SR Linux boots + compose pulls.
#
# Tuned from state/stability-ladder (Jul 2026). Override:
#   LAB_STAGGER_SECS=25  pause between steps (default)
#   LAB_STAGGER_FABRIC=0 skip fabric stagger (collectors still staggered)
#   LAB_STAGGER_COLLECTORS=0 compose up -d all at once after fabric
#   LAB_SR_CLI_TRIES_SPINE=90   sr_cli poll attempts for spine (×~2s each)
#   LAB_SR_CLI_TRIES_LEAF=120   sr_cli poll attempts for leaves
#   LAB_SR_CLI_TRIES_ALL=90     final all-node sr_cli pass
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

STAGGER_SECS="${LAB_STAGGER_SECS:-25}"
STAGGER_FABRIC="${LAB_STAGGER_FABRIC:-1}"
STAGGER_COLLECTORS="${LAB_STAGGER_COLLECTORS:-1}"
SR_CLI_TRIES_SPINE="${LAB_SR_CLI_TRIES_SPINE:-90}"
SR_CLI_TRIES_LEAF="${LAB_SR_CLI_TRIES_LEAF:-120}"
SR_CLI_TRIES_ALL="${LAB_SR_CLI_TRIES_ALL:-90}"

SRL_ORDER=("${SRL_NODES[@]}" "${CLIENT_NODES[@]}")
COLLECTOR_SERVICES=(alloy flow_dns ktranslate_snmp_srl ktranslate_flow ktranslate_sflow ktranslate_syslog gnmic)

COMPOSE=(docker compose --env-file .env --env-file compose-host.generated.env
  -f compose-base.yaml
  -f compose-groups.generated.yaml
  -f compose-catalog.generated.yaml
  -f compose-limits.generated.yaml)
# shellcheck disable=SC2207
COMPOSE+=($(bash "${ROOT}/scripts/lab-topology-exporter.sh" profile))
if bash "${ROOT}/scripts/lab-topology-exporter.sh" enabled; then
  COLLECTOR_SERVICES+=(topology_exporter)
fi

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

log_resources() {
  local wsl_avail wsl_used nctr load host_gb
  if [[ -r /proc/meminfo ]]; then
    wsl_avail=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
    wsl_used=$(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{print int((t-$2)/1024)}' /proc/meminfo)
  else
    wsl_avail=0
    wsl_used=0
  fi
  nctr=$(docker ps -q 2>/dev/null | wc -l)
  load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo "n/a n/a n/a")
  host_gb="na"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    host_gb=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.1f", $1/1024/1024/1024}' || echo "na")
  else
    local ps="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if [[ -x "$ps" ]]; then
      host_gb=$("$ps" -NoProfile -Command \
        '[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)' 2>/dev/null \
        | tr -d '\r' || echo "na")
    fi
  fi
  info "resources: host_free_gb=${host_gb} wsl_used_mb=${wsl_used} wsl_avail_mb=${wsl_avail} docker_running=${nctr} load=${load}"
}

stagger_wait() {
  info "settling ${STAGGER_SECS}s before next component..."
  log_resources
  sleep "${STAGGER_SECS}"
}

wait_sr_cli() {
  local n=$1 tries="${2:-120}"
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
  die "${n}: sr_cli not ready after ~$(( (${2:-120}) * 2 ))s (yang reload / unknown hostname — try: docker restart ${n})"
}

wait_all_sr_cli() {
  local n
  info "Waiting for sr_cli on all SRL nodes (yang-reload aware, up to $(( SR_CLI_TRIES_ALL * 2 ))s each)..."
  for n in "${SRL_NODES[@]}"; do
    wait_sr_cli "$n" "${SR_CLI_TRIES_ALL}"
    info "${n}: sr_cli ready"
  done
}

wait_sr_linux() {
  local secs="${1:-60}"
  info "Waiting for SR Linux (${secs}s)..."
  sleep "${secs}"
}

deploy_fabric() {
  info "Deploying ContainerLab topology..."
  bash "${ROOT}/scripts/clab.sh" deploy

  if [[ "${STAGGER_FABRIC}" == "1" ]]; then
    info "Staggering fabric: sequential sr_cli readiness (clab boots all nodes; no stop/start)..."
    wait_sr_cli spine1 "${SR_CLI_TRIES_SPINE}"
    info "spine1: sr_cli ready"
    stagger_wait
    for n in "${SRL_NODES[@]}"; do
      [[ "$n" == "spine1" ]] && continue
      wait_sr_cli "$n" "${SR_CLI_TRIES_LEAF}"
      info "${n}: sr_cli ready"
      stagger_wait
    done
    info "Fabric SRL nodes ready; clients up with clab deploy"
    stagger_wait
  else
    wait_sr_linux 60
  fi

  wait_all_sr_cli

  info "Applying fabric config..."
  bash "${ROOT}/scripts/apply-fabric-config.sh"
}

start_collectors() {
  info "deployment.host = $(bash "${ROOT}/scripts/host-id.sh" 2>/dev/null || hostname)"

  if [[ "${STAGGER_COLLECTORS}" == "1" ]]; then
    local svc
    for svc in "${COLLECTOR_SERVICES[@]}"; do
      info "Starting collector ${svc}..."
      lab_log_compose "up -d ${svc}"
      "${COMPOSE[@]}" up -d "${svc}"
      stagger_wait
    done
  else
    info "Starting full telemetry compose stack..."
    lab_log_compose "up -d (all collectors)"
    "${COMPOSE[@]}" up -d
  fi
}

post_up_config() {
  bash "${ROOT}/scripts/sync-snmp-discovery.sh"
  bash "${ROOT}/scripts/lab-topology-exporter.sh" post-config
  bash "${ROOT}/scripts/post-telemetry-config.sh"
}

main() {
  local up_t0; up_t0=$(date +%s)
  if [[ "${LAB_LOG_EVENTS:-1}" == "1" ]]; then
    bash "${ROOT}/scripts/lab-log-events.sh" start || true
  fi
  info "Staggered bring-up started $(date '+%Y-%m-%d %H:%M:%S') (cold run ~10 min; pause=${STAGGER_SECS}s fabric=${STAGGER_FABRIC} collectors=${STAGGER_COLLECTORS})"
  log_resources
  if [[ "${STAGGER_SKIP_FABRIC:-0}" == "1" ]]; then
    info "Skipping fabric deploy (STAGGER_SKIP_FABRIC=1)"
    wait_all_sr_cli
    bash "${ROOT}/scripts/apply-fabric-config.sh" || true
  else
    deploy_fabric
  fi
  start_collectors
  post_up_config
  log_resources
  local elapsed_s=$(( $(date +%s) - up_t0 ))
  echo ""
  echo "Staggered bring-up complete at $(date '+%Y-%m-%d %H:%M:%S') ($(( elapsed_s / 60 ))m $(( elapsed_s % 60 ))s elapsed)."
}

main "$@"
