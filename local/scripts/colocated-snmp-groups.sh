#!/usr/bin/env bash
# Install three site-scoped SNMP credential groups for LAB_FABRIC_PROFILE=colocated.
# Laptop profile uses groups/srl-hq.env (AWS-aligned HQ site). Colocated adds branch groups.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"
# shellcheck source=snmp-group-utils.sh
source "${ROOT}/scripts/snmp-group-utils.sh"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ "${LAB_FABRIC_PROFILE:-}" == "colocated" ]] \
  || die "colocated-snmp-groups.sh requires LAB_FABRIC_PROFILE=colocated"

for sample in srl-hq srl-branch1 srl-branch2; do
  src="${ROOT}/groups/${sample}.env.sample"
  dst="${ROOT}/groups/${sample}.env"
  [[ -f "${src}" ]] || die "missing ${src}"
  if [[ ! -f "${dst}" ]]; then
    cp "${src}" "${dst}"
    normalize_env_file "${dst}"
    info "installed ${dst}"
  else
    normalize_env_file "${dst}"
    info "present ${dst}"
  fi
done

# Legacy single-group file conflicts with site groups (duplicate devices / ports).
if [[ -f "${ROOT}/groups/srl.env" ]]; then
  bak="${ROOT}/groups/srl.env.single-group.bak"
  if [[ ! -f "${bak}" ]]; then
    mv "${ROOT}/groups/srl.env" "${bak}"
    info "moved legacy groups/srl.env -> $(basename "${bak}") (colocated uses site groups)"
  else
    rm -f "${ROOT}/groups/srl.env"
    info "removed legacy groups/srl.env (backup already exists)"
  fi
fi

bash "${ROOT}/scripts/generate-groups.sh"
info "colocated SNMP groups ready (srl-hq, srl-branch1, srl-branch2)"
