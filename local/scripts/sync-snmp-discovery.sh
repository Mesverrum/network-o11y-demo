#!/usr/bin/env bash
# sync-snmp-discovery.sh — golden-path SNMP discovery for the local compose lab.
#
# 1. Sync clab mgmt CIDR → groups/*.env TARGETS (or NetBox bootstrap)
# 2. Run ktranslate discover_<group> for every credential group
# 3. Reload flow/syslog/SNMP pollers when device lists change
#
# Called from make up, stabilize, and snmp-recover. Fails hard if discovery
# returns zero devices (no silent stale state/devices-*.yaml).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

bash "${ROOT}/scripts/ensure-snmp-groups.sh"
[[ -f compose-groups.generated.yaml ]] || die "missing compose-groups.generated.yaml — run: make generate"

# Alloy must be up — discover_* containers export OTLP and depend on it (compose path).
if ! docker compose --env-file .env --env-file compose-host.generated.env \
  -f compose-base.yaml -f compose-groups.generated.yaml \
  -f compose-catalog.generated.yaml ps --status running --services 2>/dev/null \
  | grep -qx alloy; then
  die "alloy is not running — start collectors before SNMP discovery (make up / stabilize)"
fi

netbox_mode=0
while IFS= read -r _ge; do
  if grep -q '^DISCOVERY_SOURCE=netbox' "${_ge}" 2>/dev/null; then
    netbox_mode=1
    break
  fi
done < <(snmp_group_env_files "${ROOT}")

if [[ "${netbox_mode}" -eq 1 ]]; then
  info "NetBox discovery source"
  bash "${ROOT}/scripts/netbox-bootstrap.sh"
else
  info "CIDR discovery — sync clab mgmt subnet to groups/*.env TARGETS"
  bash "${ROOT}/scripts/update-snmp-targets.sh"
fi

info "SNMP discovery (scan TARGETS → state/devices-*.yaml)"
if ! bash "${ROOT}/scripts/run-discovery-all.sh"; then
  die "SNMP discovery failed — run: make snmp-check"
fi

info "SNMP discovery complete"
