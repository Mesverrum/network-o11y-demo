#!/usr/bin/env bash
# Ensure groups/srl-hq.env exists (laptop + AWS-aligned default). Migrates legacy groups/srl.env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

HQ_ENV="${ROOT}/groups/srl-hq.env"
HQ_SAMPLE="${ROOT}/groups/srl-hq.env.sample"
LEGACY_ENV="${ROOT}/groups/srl.env"
LEGACY_SAMPLE="${ROOT}/groups/srl.env.sample"

_migrate_legacy_snmp_state() {
  local root="$1"
  local legacy_dev="${root}/state/devices-srl.yaml"
  local hq_dev="${root}/state/devices-srl-hq.yaml"
  if [[ -f "${legacy_dev}" && ! -f "${hq_dev}" ]]; then
    cp "${legacy_dev}" "${hq_dev}"
    info "copied state/devices-srl.yaml → state/devices-srl-hq.yaml"
  fi
  local f
  for f in discovery-srl poller-srl; do
    if [[ -f "${root}/state/${f}.runtime.yaml" && ! -f "${root}/state/${f}-hq.runtime.yaml" ]]; then
      cp "${root}/state/${f}.runtime.yaml" "${root}/state/${f}-hq.runtime.yaml"
      info "copied state/${f}.runtime.yaml → state/${f}-hq.runtime.yaml"
    fi
  done
}

if [[ -f "${HQ_ENV}" ]]; then
  _migrate_legacy_snmp_state "${ROOT}"
  exit 0
fi

if [[ -f "${LEGACY_ENV}" ]]; then
  bak="${ROOT}/groups/srl.env.legacy.bak"
  cp "${LEGACY_ENV}" "${HQ_ENV}"
  if grep -q '^GROUP=srl$' "${HQ_ENV}" 2>/dev/null; then
    sed -i 's/^GROUP=srl$/GROUP=srl-hq/' "${HQ_ENV}"
  fi
  if ! grep -q '^SITE=' "${HQ_ENV}" 2>/dev/null; then
    echo 'SITE=hq' >> "${HQ_ENV}"
  fi
  if [[ ! -f "${bak}" ]]; then
    mv "${LEGACY_ENV}" "${bak}"
    info "migrated groups/srl.env → groups/srl-hq.env (backup: groups/srl.env.legacy.bak)"
  else
    rm -f "${LEGACY_ENV}"
    info "migrated groups/srl.env → groups/srl-hq.env (backup already exists)"
  fi
  _migrate_legacy_snmp_state "${ROOT}"
  exit 0
fi

[[ -f "${HQ_SAMPLE}" ]] || die "missing ${HQ_SAMPLE}"
cp "${HQ_SAMPLE}" "${HQ_ENV}"
info "installed ${HQ_ENV} from sample"
