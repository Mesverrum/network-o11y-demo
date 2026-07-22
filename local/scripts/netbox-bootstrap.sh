#!/usr/bin/env bash
# Populate NetBox Cloud with lab topology and sync clab mgmt IPs when fabric is up.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ -n "${NETBOX_TOKEN:-}" ]] || die "NETBOX_TOKEN not set in .env"
[[ -n "${NETBOX_API_URL:-}" ]] || die "NETBOX_API_URL not set in .env"

info "Populating NetBox Cloud inventory..."
python3 "${ROOT}/scripts/netbox-populate.py"

if docker inspect spine1 >/dev/null 2>&1; then
  info "Syncing ContainerLab mgmt IPs to NetBox primary_ip4..."
  python3 "${ROOT}/scripts/update-netbox-mgmt-ips.py"
else
  info "ContainerLab nodes not running — skip mgmt IP sync (run: make netbox-sync-mgmt after clab up)"
fi

ui="${NETBOX_HOST_URL:-${NETBOX_URL:-}}"
info "NetBox inventory synced — ${ui:-see NETBOX_HOST_URL in .env}"
