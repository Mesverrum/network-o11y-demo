#!/usr/bin/env bash
# Stage topology + fabric configs for the active LAB_FABRIC_PROFILE into paths
# ContainerLab expects (topology.clab.yml + configs/fabric/).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ -f "${CLAB_TOPOLOGY_SOURCE}" ]] || die "missing ${CLAB_TOPOLOGY_SOURCE}"
[[ -d "${FABRIC_SOURCE_DIR}" ]] || die "missing ${FABRIC_SOURCE_DIR}"

mkdir -p "${LAB_REPO_ROOT}/configs/fabric"
rsync -a --delete "${FABRIC_SOURCE_DIR}/" "${LAB_REPO_ROOT}/configs/fabric/"
cp -f "${CLAB_TOPOLOGY_SOURCE}" "${LAB_REPO_ROOT}/topology.clab.yml"

if [[ "${CLAB_USE_EXT4}" == "1" ]]; then
  mkdir -p "${CLAB_DEPLOY_DIR}/configs/fabric"
  rsync -a --delete "${FABRIC_SOURCE_DIR}/" "${CLAB_DEPLOY_DIR}/configs/fabric/"
  cp -f "${CLAB_TOPOLOGY_SOURCE}" "${CLAB_DEPLOY_DIR}/topology.clab.yml"
fi

info "staged LAB_FABRIC_PROFILE=${LAB_FABRIC_PROFILE} (${#SRL_NODES[@]} SRL + ${#CLIENT_NODES[@]} clients)"
