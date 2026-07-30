#!/usr/bin/env bash
# Resolve fabric node lists and paths from LAB_FABRIC_PROFILE.
#   laptop     — 1 spine + 2 leaves + 2 clients (16 GB friendly)
#   colocated  — HQ hub + 2 branch offices (AWS demo)
set -euo pipefail

fabric_profile_init() {
  [[ -n "${_FABRIC_PROFILE_INIT:-}" ]] && return 0
  _FABRIC_PROFILE_INIT=1

  if [[ -z "${LAB_REPO_ROOT:-}" ]]; then
    LAB_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi

  if [[ -f "${LAB_REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${LAB_REPO_ROOT}/.env"
    set +a
  fi

  case "${LAB_FABRIC_PROFILE:-laptop}" in
    colocated|hq-branches|aws)
      LAB_FABRIC_PROFILE=colocated
      SRL_NODES=(spine1 leaf1 leaf2 leaf-br1 leaf-br2)
      CLIENT_NODES=(client1 client2 client-br1 client-br2)
      FABRIC_SOURCE_DIR="${LAB_REPO_ROOT}/configs/fabric-colocated"
      CLAB_TOPOLOGY_SOURCE="${LAB_REPO_ROOT}/topology-colocated.clab.yml"
      GNMIC_CONFIG="${LAB_REPO_ROOT}/gnmic/gnmic-colocated.yaml"
      FLOW_DNS_DOCKER_NODES=(spine1 leaf1 leaf2 leaf-br1 leaf-br2 client1 client2 client-br1 client-br2)
      ;;
    laptop|*)
      LAB_FABRIC_PROFILE=laptop
      SRL_NODES=(spine1 leaf1 leaf2)
      CLIENT_NODES=(client1 client2)
      FABRIC_SOURCE_DIR="${LAB_REPO_ROOT}/configs/fabric"
      CLAB_TOPOLOGY_SOURCE="${LAB_REPO_ROOT}/topology.clab.yml"
      GNMIC_CONFIG="${LAB_REPO_ROOT}/gnmic/gnmic.yaml"
      FLOW_DNS_DOCKER_NODES=(spine1 leaf1 leaf2 client1 client2)
      ;;
  esac

  ALL_FABRIC_NODES=("${SRL_NODES[@]}" "${CLIENT_NODES[@]}")
  export LAB_FABRIC_PROFILE SRL_NODES CLIENT_NODES FABRIC_SOURCE_DIR CLAB_TOPOLOGY_SOURCE GNMIC_CONFIG FLOW_DNS_DOCKER_NODES ALL_FABRIC_NODES
}

fabric_profile_init

# Site label for topology-exporter / dashboards (colocated only).
fabric_site_for_node() {
  local n="$1"
  case "$n" in
    spine1|leaf1|leaf2|client1|client2) echo hq ;;
    leaf-br1|client-br1) echo branch1 ;;
    leaf-br2|client-br2) echo branch2 ;;
    *) echo unknown ;;
  esac
}

fabric_role_for_node() {
  local n="$1"
  case "$n" in
    spine1) echo spine ;;
    leaf1|leaf2) echo leaf ;;
    leaf-br1|leaf-br2) echo branch-edge ;;
    client*) echo server ;;
    *) echo unknown ;;
  esac
}
