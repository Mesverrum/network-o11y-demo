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

FABRIC_STAGING_DIR="${LAB_REPO_ROOT}/configs/fabric"
TOPOLOGY_STAGING="${LAB_REPO_ROOT}/topology.clab.yml"

# Laptop profile keeps configs in configs/fabric/ already; colocated copies from fabric-colocated/.
if [[ "$(realpath "${FABRIC_SOURCE_DIR}")" != "$(realpath "${FABRIC_STAGING_DIR}")" ]]; then
  mkdir -p "${FABRIC_STAGING_DIR}"
  rm -rf "${FABRIC_STAGING_DIR}"/*
  cp -a "${FABRIC_SOURCE_DIR}/." "${FABRIC_STAGING_DIR}/"
fi
if [[ "$(realpath "${CLAB_TOPOLOGY_SOURCE}")" != "$(realpath "${TOPOLOGY_STAGING}")" ]]; then
  cp -f "${CLAB_TOPOLOGY_SOURCE}" "${TOPOLOGY_STAGING}"
fi

if [[ "${CLAB_USE_EXT4}" == "1" ]]; then
  mkdir -p "${CLAB_DEPLOY_DIR}/configs/fabric"
  rm -rf "${CLAB_DEPLOY_DIR}/configs/fabric"/*
  cp -a "${FABRIC_SOURCE_DIR}/." "${CLAB_DEPLOY_DIR}/configs/fabric/"
  cp -f "${CLAB_TOPOLOGY_SOURCE}" "${CLAB_DEPLOY_DIR}/topology.clab.yml"
fi

info "staged LAB_FABRIC_PROFILE=${LAB_FABRIC_PROFILE} (${#SRL_NODES[@]} SRL + ${#CLIENT_NODES[@]} clients)"
