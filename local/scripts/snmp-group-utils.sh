#!/usr/bin/env bash
# Helpers for multi-group SNMP (compose + k3s).
set -euo pipefail

snmp_group_env_files() {
  local root="${1:-}"
  shopt -s nullglob
  local files=("${root}/groups"/*.env)
  shopt -u nullglob
  if [[ ${#files[@]} -eq 0 ]]; then
    return 1
  fi
  printf '%s\n' "${files[@]}"
}

snmp_group_names() {
  local root="${1:-}" f group
  while IFS= read -r f; do
    group="$(awk -F= '/^GROUP=/{print $2; exit}' "${f}")"
    [[ -n "${group}" ]] && echo "${group}"
  done < <(snmp_group_env_files "${root}")
}

k8s_snmp_deployment_names() {
  local root="${1:-}" group
  while IFS= read -r group; do
    echo "ktranslate-snmp-${group}"
  done < <(snmp_group_names "${root}")
}

# TRAP_PORT for a fabric node from its SITE= group file (fallback 1620).
snmp_trap_port_for_node() {
  local root="$1" node="$2"
  # shellcheck source=fabric-nodes.sh
  source "${root}/scripts/fabric-nodes.sh"
  local site group_env
  site="$(fabric_site_for_node "${node}")"
  while IFS= read -r group_env; do
    local gsite port
    gsite="$(awk -F= '/^SITE=/{print $2; exit}' "${group_env}")"
    [[ "${gsite}" == "${site}" ]] || continue
    port="$(awk -F= '/^TRAP_PORT=/{print $2; exit}' "${group_env}")"
    [[ -n "${port}" ]] && echo "${port}" && return 0
  done < <(snmp_group_env_files "${root}")
  echo "1620"
}

snmp_total_discovered_devices() {
  local root="$1" total=0 f n
  shopt -s nullglob
  for f in "${root}/state"/devices-*.yaml; do
    n="$(yq 'length' "${f}" 2>/dev/null || echo 0)"
    [[ "${n}" =~ ^[0-9]+$ ]] || n=0
    total=$((total + n))
  done
  shopt -u nullglob
  echo "${total}"
}
