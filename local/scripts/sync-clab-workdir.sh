#!/usr/bin/env bash
# Mirror topology + fabric configs to an ext4 workdir when the repo is on /mnt/c.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

info() { echo "==> $*"; }

if [[ "$CLAB_USE_EXT4" != "1" ]]; then
  info "Repo on native FS ($(findmnt -n -o FSTYPE -T "$LAB_REPO_ROOT" 2>/dev/null || echo ext4)); clab uses ${LAB_REPO_ROOT}"
  exit 0
fi

info "Syncing ContainerLab workdir to ext4: ${CLAB_DEPLOY_DIR}"
mkdir -p "${CLAB_DEPLOY_DIR}/configs/fabric"
rsync -a --delete "${LAB_REPO_ROOT}/configs/fabric/" "${CLAB_DEPLOY_DIR}/configs/fabric/"
rsync -a "${LAB_REPO_ROOT}/topology.clab.yml" "${CLAB_DEPLOY_DIR}/topology.clab.yml"
info "Synced topology.clab.yml + configs/fabric/ ($(find "${CLAB_DEPLOY_DIR}/configs/fabric" -maxdepth 1 -name '*.cfg' | wc -l) node configs)"
