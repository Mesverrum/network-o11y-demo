#!/usr/bin/env bash
# lab-down.sh — make down with audit logging (compose down + clab destroy).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

COMPOSE=(docker compose --env-file .env --env-file compose-host.generated.env
  -f compose-base.yaml
  -f compose-groups.generated.yaml
  -f compose-catalog.generated.yaml
  -f compose-limits.generated.yaml)
# shellcheck disable=SC2207
COMPOSE+=($(bash "${ROOT}/scripts/lab-topology-exporter.sh" profile 2>/dev/null || true))

bash "${ROOT}/scripts/fabric-watch.sh" stop || true
bash "${ROOT}/scripts/lab-log-events.sh" stop || true
bash "${ROOT}/scripts/events-loop.sh" stop || true
bash "${ROOT}/scripts/traffic.sh" stop || true
bash "${ROOT}/scripts/internet-probes.sh" stop || true

echo "==> Stopping compose..."
lab_log_compose "down"
"${COMPOSE[@]}" down || true

echo "==> Destroying ContainerLab topology..."
bash "${ROOT}/scripts/clab.sh" destroy || true

lab_log_action down "complete"
