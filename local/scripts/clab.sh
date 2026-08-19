#!/usr/bin/env bash
# ContainerLab wrapper: deploy/destroy/inspect from ext4 workdir when repo is on drvfs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"

clab_topo_file() {
  if [[ "${LAB_FABRIC_PROFILE}" == "snmp-min" ]]; then
    echo topology-snmp-min.clab.yml
  else
    echo topology.clab.yml
  fi
}

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
  local topo
  topo="$(clab_topo_file)"
  echo "==> ${bin} deploy from ${dir} -t ${topo}"
  lab_log_clab "deploy from ${dir} topo=${topo} extra_args=$*"
  (cd "$dir" && lab_run "$bin" deploy -t "${topo}" "$@")
}

destroy() {
  local bin dir topo
  bin=$(clab_bin)
  for dir in "$CLAB_DEPLOY_DIR" "$LAB_REPO_ROOT"; do
    for topo in topology.clab.yml topology-snmp-min.clab.yml topology-colocated.clab.yml; do
      [[ -f "${dir}/${topo}" ]] || continue
      echo "==> ${bin} destroy in ${dir} -t ${topo}"
      lab_log_clab "destroy in ${dir} topo=${topo} extra_args=$*"
      (cd "$dir" && lab_run "$bin" destroy -t "${topo}" --cleanup "$@") || true
    done
  done
}

inspect() {
  local bin dir topo
  bin=$(clab_bin)
  dir="$CLAB_DEPLOY_DIR"
  topo="$(clab_topo_file)"
  if [[ ! -f "${dir}/${topo}" ]]; then
    dir="$LAB_REPO_ROOT"
  fi
  (cd "$dir" && "$bin" inspect -t "${topo}" "$@")
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
