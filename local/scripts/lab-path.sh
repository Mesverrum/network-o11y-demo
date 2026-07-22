#!/usr/bin/env bash
# Resolve ContainerLab deploy directory. When the repo is on WSL drvfs (/mnt/c),
# fabric startup-config and clab labdir must live on native ext4 or postdeploy fails.
lab_path_init() {
  [[ -n "${_LAB_PATH_INIT:-}" ]] && return 0
  _LAB_PATH_INIT=1

  if [[ -z "${LAB_REPO_ROOT:-}" ]]; then
    LAB_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi

  if [[ -f "${LAB_REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${LAB_REPO_ROOT}/.env"
    set +a
  fi

  lab_fs_type() {
    findmnt -n -o FSTYPE -T "$1" 2>/dev/null || echo unknown
  }

  lab_is_drvfs() {
    local t
    t=$(lab_fs_type "$1")
    [[ "$t" == "9p" || "$t" == "drvfs" ]]
  }

  CLAB_EXT4_ROOT="${CLAB_EXT4_ROOT:-${HOME}/.cache/network-o11y-demo/clab}"
  if lab_is_drvfs "$LAB_REPO_ROOT" || [[ "${CLAB_FORCE_EXT4:-}" == "1" ]]; then
    CLAB_DEPLOY_DIR="$CLAB_EXT4_ROOT"
    CLAB_USE_EXT4=1
  else
    CLAB_DEPLOY_DIR="$LAB_REPO_ROOT"
    CLAB_USE_EXT4=0
  fi

  export LAB_REPO_ROOT CLAB_DEPLOY_DIR CLAB_USE_EXT4 CLAB_EXT4_ROOT
}

lab_path_init
