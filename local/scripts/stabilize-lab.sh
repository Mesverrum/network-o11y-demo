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

need_deploy=0
for n in "${SRL[@]}"; do
  if ! docker inspect "$n" >/dev/null 2>&1; then
    need_deploy=1
    break
  fi
done

if (( need_deploy )); then
  info "SRL containers missing — deploying topology (no --reconfigure)..."
  clab deploy -t topology.clab.yml 2>/dev/null || containerlab deploy -t topology.clab.yml
else
  info "Starting stopped SRL nodes (if any)..."
  for n in "${SRL[@]}"; do
    if [[ "$(docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null || echo false)" != "true" ]]; then
      docker start "$n"
    fi
  done
fi

info "Waiting for SR Linux (45s)..."
sleep 45

bash "${ROOT}/scripts/apply-fabric-config.sh"

info "Telemetry compose stack..."
docker compose --env-file .env \
  -f compose-base.yaml \
  -f compose-groups.generated.yaml \
  -f compose-limits.generated.yaml up -d

if grep -q '^DISCOVERY_SOURCE=netbox' "${ROOT}/groups/srl.env" 2>/dev/null; then
  bash "${ROOT}/scripts/netbox-bootstrap.sh" || {
    info "NetBox bootstrap failed — trying mgmt-only sync"
    set -a && . "${ROOT}/.env" && set +a
    python3 "${ROOT}/scripts/update-netbox-mgmt-ips.py" || true
  }
else
  bash "${ROOT}/scripts/update-snmp-targets.sh"
fi

./scripts/run-discovery.sh srl || info "discovery returned 0 devices — check SNMP + NetBox mgmt IPs"
bash "${ROOT}/scripts/update-topology-targets.sh"
bash "${ROOT}/scripts/softflowd.sh"
bash "${ROOT}/scripts/syslog-config.sh" || info "syslog config skipped"
bash "${ROOT}/scripts/snmp-trap-config.sh" || info "trap config skipped"

info "Lab stabilized. Run: make traffic && make status"
