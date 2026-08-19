#!/usr/bin/env bash
# Start Orb agent sidecar (dry-run SNMP discovery by default).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ORB="${ROOT}/orb"
ENV_FILE="${ROOT}/.env"

info() { echo "==> $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker required"
docker compose version >/dev/null || die "docker compose plugin required"

# Load .env without printing secrets
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(sed 's/\r$//' "$ENV_FILE" | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' || true)
  set +a
fi

export ORB_DRY_RUN="${ORB_DRY_RUN:-1}"
export ORB_SNMP_TARGETS="${ORB_SNMP_TARGETS:-172.20.20.0/24}"
export ORB_SNMP_COMMUNITY="${ORB_SNMP_COMMUNITY:-${SNMP_V2_COMMUNITY:-public}}"
export ORB_PKTVISOR="${ORB_PKTVISOR:-0}"
export ORB_AGENT_IMAGE="${ORB_AGENT_IMAGE:-netboxlabs/orb-agent:latest}"

if [[ "${ORB_DRY_RUN}" == "0" ]]; then
  [[ -n "${DIODE_CLIENT_ID:-}" && -n "${DIODE_CLIENT_SECRET:-}" ]] \
    || die "ORB_DRY_RUN=0 requires DIODE_CLIENT_ID and DIODE_CLIENT_SECRET in .env"
fi

mkdir -p "${ORB}/out"
python3 "${ROOT}/scripts/orb-render-config.py"

info "pulling ${ORB_AGENT_IMAGE}"
docker pull "${ORB_AGENT_IMAGE}"

info "starting orb-agent (network_mode=host)"
ENV_GEN="${ORB}/.compose.env"
{
  echo "ORB_AGENT_IMAGE=${ORB_AGENT_IMAGE}"
  echo "ORB_SNMP_COMMUNITY=${ORB_SNMP_COMMUNITY}"
  echo "DIODE_CLIENT_ID=${DIODE_CLIENT_ID:-}"
  echo "DIODE_CLIENT_SECRET=${DIODE_CLIENT_SECRET:-}"
} >"$ENV_GEN"
# Always recreate so agent.generated.yaml volume bind picks up render changes.
( cd "$ORB" && docker compose -f compose.yaml --env-file "$ENV_GEN" up -d --force-recreate )

info "waiting for first dry-run / discovery cycle (up to 3m)"
ok=0
no_hosts=0
if [[ "${ORB_DRY_RUN}" != "1" ]]; then
  info "live Diode mode — skipping dry-run JSON wait"
  sleep 8
  docker logs orb-agent --tail 40 || true
else
for i in $(seq 1 36); do
  if ls -1 "${ORB}/out"/*.json >/dev/null 2>&1; then
    # Ignore stale files older than this bring-up if agent just started
    if find "${ORB}/out" -name '*.json' -mmin -5 2>/dev/null | grep -q .; then
      ok=1
      break
    fi
  fi
  # still starting?
  if ! docker ps --format '{{.Names}}' | grep -qx orb-agent; then
    docker logs orb-agent --tail 40 || true
    die "orb-agent container not running"
  fi
  if docker logs orb-agent --since 5m 2>&1 | grep -qE 'responsive_target_count":"[1-9]|SNMP probe scan complete'; then
    # Probe found hosts — give discovery more time to emit dry-run JSON
    :
  elif docker logs orb-agent --since 5m 2>&1 | grep -q "no hosts responded to SNMP probe"; then
    no_hosts=1
    break
  fi
  sleep 5
done

if [[ "$ok" == "1" ]]; then
  info "dry-run outputs:"
  ls -lt "${ORB}/out"/*.json | head -10
else
  info "no JSON yet (dry_run=${ORB_DRY_RUN}). Recent logs:"
  docker logs orb-agent --tail 30 || true
  if docker logs orb-agent --since 10m 2>&1 | grep -qE 'responsive_target_count":"[1-9]'; then
    info "SNMP hosts responded; discovery may still be writing dry-run JSON — check ${ORB}/out shortly."
  else
    info "Fabric SNMP may be down (no devices on ${ORB_SNMP_TARGETS}). Agent is running; re-check after fabric is up."
  fi
fi
fi

info "logs: make -C local orb-logs"
info "config: ${ORB}/agent.generated.yaml"
