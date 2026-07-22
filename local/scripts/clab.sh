#!/usr/bin/env bash
# ContainerLab wrapper: deploy/destroy/inspect from ext4 workdir when repo is on drvfs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

cmd="${1:-}"
shift || true

clab_bin() {
  if command -v containerlab >/dev/null 2>&1; then
    echo containerlab
  else
    echo clab
  fi
}

deploy() {
  bash "${ROOT}/scripts/sync-clab-workdir.sh"
  local bin dir
  bin=$(clab_bin)
  dir="$CLAB_DEPLOY_DIR"
  echo "==> ${bin} deploy from ${dir}"
  (cd "$dir" && "$bin" deploy -t topology.clab.yml "$@")
}

destroy() {
  local bin
  bin=$(clab_bin)
  for dir in "$CLAB_DEPLOY_DIR" "$LAB_REPO_ROOT"; do
    [[ -f "${dir}/topology.clab.yml" ]] || continue
    echo "==> ${bin} destroy in ${dir}"
    (cd "$dir" && "$bin" destroy -t topology.clab.yml --cleanup "$@") || true
  done
}

inspect() {
  local bin dir
  bin=$(clab_bin)
  dir="$CLAB_DEPLOY_DIR"
  if [[ ! -f "${dir}/topology.clab.yml" ]]; then
    dir="$LAB_REPO_ROOT"
  fi
  (cd "$dir" && "$bin" inspect -t topology.clab.yml "$@")
}

case "$cmd" in
  deploy)  deploy "$@" ;;
  destroy) destroy "$@" ;;
  inspect) inspect "$@" ;;
  *)
    echo "usage: clab.sh deploy|destroy|inspect [extra clab args...]" >&2
    exit 1
    ;;
esac
