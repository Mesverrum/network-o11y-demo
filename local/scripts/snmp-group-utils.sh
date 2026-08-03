#!/usr/bin/env bash
# Helpers for multi-group SNMP (compose + k3s).
set -euo pipefail

# Windows checkouts may leave CRLF in *.env.sample; sourcing breaks on Linux.
normalize_env_file() {
  local f="$1"
  [[ -f "${f}" ]] || return 0
  if grep -q $'\r' "${f}" 2>/dev/null; then
    sed -i 's/\r$//' "${f}"
  fi
}

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

# Compose service name for one credential group (e.g. ktranslate_snmp_srl-hq).
snmp_poller_service_name() {
  echo "ktranslate_snmp_${1}"
}

snmp_poller_compose_services() {
  local root="${1:-}" group
  while IFS= read -r group; do
    snmp_poller_service_name "${group}"
  done < <(snmp_group_names "${root}")
}

# HQ site group when present; else first configured group.
primary_snmp_group() {
  local root="${1:-}" names
  names="$(snmp_group_names "${root}" 2>/dev/null || true)"
  if [[ -z "${names}" ]]; then
    echo "srl-hq"
    return 0
  fi
  if grep -qx 'srl-hq' <<<"${names}"; then
    echo "srl-hq"
    return 0
  fi
  echo "${names}" | head -1
}

snmp_group_env_for() {
  local root="$1" group="${2:-}"
  [[ -n "${group}" ]] || group="$(primary_snmp_group "${root}")"
  echo "${root}/groups/${group}.env"
}

k8s_snmp_deployment_names() {
  local root="${1:-}" group
  while IFS= read -r group; do
    echo "ktranslate-snmp-${group}"
  done < <(snmp_group_names "${root}")
}

# First running compose SNMP poller container id (any group).
snmp_poller_container_id() {
  docker ps -qf 'name=ktranslate_snmp' | head -1
}

snmp_poller_container_name() {
  local cid
  cid="$(snmp_poller_container_id)"
  [[ -n "${cid}" ]] || return 1
  docker inspect -f '{{.Name}}' "${cid}" | sed 's#^/##'
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
