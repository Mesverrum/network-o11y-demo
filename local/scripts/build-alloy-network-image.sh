#!/usr/bin/env bash
# build-alloy-network-image.sh — overlay curated snmp.yml onto grafana/alloy:latest.
#
# Source: sibling clone of the grafana/alloy fork (branch network-snmp).
# SNMP library SoT is Mesverrum/snmp-sd when that sibling exists (Nokia
# hot/cold/topology split). Set SNMP_LIB_SRC= or SKIP_SNMP_CONVERT=1 to
# skip re-running convert.py (a full convert overwrites the curated split).
#   ALLOY_SRC=/path/to/alloy ./scripts/build-alloy-network-image.sh
#
# Then in local/.env:
#   ALLOY_IMAGE=srl-local/alloy:network-dev
#   LAB_ALLOY_SNMP=1
# Recreate: make -C local alloy-snmp-up
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${ALLOY_NETWORK_TAG:-srl-local/alloy:network-dev}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

command -v docker >/dev/null || die "docker required"
command -v python3 >/dev/null || command -v python >/dev/null || die "python3 required"
PY="$(command -v python3 || command -v python)"

resolve_alloy_src() {
  if [[ -n "${ALLOY_SRC:-}" && -d "${ALLOY_SRC}/.git" ]]; then
    echo "${ALLOY_SRC}"
    return 0
  fi
  local c
  for c in \
    "$(cd "${ROOT}/../.." && pwd)/alloy" \
    "/mnt/c/Users/mesve/projects/alloy" \
    "${HOME}/projects/alloy" \
    "${HOME}/alloy"
  do
    if [[ -d "${c}/.git" && -f "${c}/Dockerfile.network" ]]; then
      echo "${c}"
      return 0
    fi
  done
  return 1
}

resolve_snmp_lib() {
  if [[ -n "${SNMP_LIB_SRC:-}" && -f "${SNMP_LIB_SRC}/snmp/modules/nokia/nokia_srlinux.yml" ]]; then
    echo "${SNMP_LIB_SRC}"
    return 0
  fi
  local c
  for c in \
    "$(cd "${ROOT}/../.." && pwd)/snmp-sd" \
    "/mnt/c/Users/mesve/projects/snmp-sd" \
    "${HOME}/projects/snmp-sd" \
    "${HOME}/snmp-sd"
  do
    if [[ -f "${c}/snmp/modules/nokia/nokia_srlinux_sensors.yml" ]]; then
      echo "${c}"
      return 0
    fi
  done
  return 1
}

SRC="$(resolve_alloy_src)" || die "Alloy fork not found. Clone https://github.com/Mesverrum/alloy (branch network-snmp) as a sibling, or set ALLOY_SRC"

[[ -f "${SRC}/Dockerfile.network" ]] || die "missing ${SRC}/Dockerfile.network — checkout branch network-snmp"
if [[ "${ALLOY_NETWORK_FROM_SOURCE:-0}" != "1" ]]; then
  [[ -f "${SRC}/tools/snmp-profile-convert/convert.py" ]] || die "missing converter in ${SRC}"
fi

info "Using Alloy fork: ${SRC}"
LIB="$(resolve_snmp_lib || true)"
if [[ -n "${LIB}" && "${SKIP_SNMP_CONVERT:-1}" != "0" ]]; then
  info "SNMP library from ${LIB} (skip convert — Nokia hot/cold/topology split)"
  cp -a "${LIB}/snmp/." "${SRC}/snmp/"
else
  info "Regenerating snmp modules..."
  CONVERT_ARGS=()
  # Prefer full kentik/snmp-profiles tree when present (sibling clone).
  for kentik in \
    "${KENTIK_SNMP_PROFILES:-}" \
    "$(cd "${SRC}/.." && pwd)/snmp-profiles/profiles/kentik_snmp" \
    "/mnt/c/Users/mesve/projects/snmp-profiles/profiles/kentik_snmp" \
    "${HOME}/projects/snmp-profiles/profiles/kentik_snmp"
  do
    if [[ -n "${kentik}" && -d "${kentik}" ]]; then
      CONVERT_ARGS+=(--profiles "${kentik}" --clean-modules)
      info "Profiles from: ${kentik}"
      break
    fi
  done
  "${PY}" "${SRC}/tools/snmp-profile-convert/convert.py" "${CONVERT_ARGS[@]+"${CONVERT_ARGS[@]}"}"
fi

info "Building ${TAG}..."
DF="Dockerfile.network"
if [[ "${ALLOY_NETWORK_FROM_SOURCE:-0}" == "1" ]]; then
  # Full BuildKit Dockerfile.network-src pulls ~2GB alloy-build-image (slow).
  # Default lab path: compile Alloy on the host and overlay onto grafana/alloy:latest.
  if [[ "${ALLOY_NETWORK_FULL_DOCKERFILE:-0}" == "1" ]]; then
    DF="Dockerfile.network-src"
    info "FROM_SOURCE=1 FULL_DOCKERFILE=1 → ${DF}"
    export DOCKER_BUILDKIT=1
    docker build -f "${SRC}/${DF}" -t "${TAG}" "${SRC}"
  else
    info "FROM_SOURCE=1 → host go build + binary overlay (includes discovery.snmp)"
    ALLOY_SRC="${SRC}" ALLOY_NETWORK_TAG="${TAG}" \
      bash "${ROOT}/scripts/build-alloy-bin-overlay.sh"
  fi
else
  info "overlay ${DF} (stock Alloy + snmp.yml + snmp-discovery CLI; no discovery.snmp)"
  docker build -f "${SRC}/${DF}" -t "${TAG}" "${SRC}"
fi

mkdir -p "${ROOT}/alloy" "${ROOT}/fixtures/alloy-snmp"
cp -f "${SRC}/snmp/snmp-network.yml" "${ROOT}/alloy/snmp-network.yml"
cp -f "${SRC}/snmp/snmp-network.yml" "${ROOT}/fixtures/alloy-snmp/snmp-network.yml"
cp -f "${SRC}/snmp/sysobjectid-index.yaml" "${ROOT}/fixtures/alloy-snmp/sysobjectid-index.yaml"
if [[ -f "${SRC}/snmp/fingerprinters.yml" ]]; then
  cp -f "${SRC}/snmp/fingerprinters.yml" "${ROOT}/fixtures/alloy-snmp/fingerprinters.yml"
fi
if [[ -f "${SRC}/snmp/module-tiers.yaml" ]]; then
  cp -f "${SRC}/snmp/module-tiers.yaml" "${ROOT}/fixtures/alloy-snmp/module-tiers.yaml"
fi
if [[ -f "${SRC}/snmp/auths.yml" ]]; then
  cp -f "${SRC}/snmp/auths.yml" "${ROOT}/fixtures/alloy-snmp/auths.yml"
fi
if [[ -f "${SRC}/snmp/auths.example.yml" ]]; then
  cp -f "${SRC}/snmp/auths.example.yml" "${ROOT}/fixtures/alloy-snmp/auths.example.yml"
fi
if [[ -d "${SRC}/snmp/modules" ]]; then
  rm -rf "${ROOT}/fixtures/alloy-snmp/modules"
  cp -a "${SRC}/snmp/modules" "${ROOT}/fixtures/alloy-snmp/modules"
fi
if [[ -f "${SRC}/snmp/fingerprinters.yml" ]]; then
  cp -f "${SRC}/snmp/fingerprinters.yml" "${ROOT}/alloy/fingerprinters.yml"
  cp -f "${SRC}/snmp/fingerprinters.yml" "${ROOT}/fixtures/alloy-snmp/fingerprinters.yml"
fi
if [[ ! -f "${ROOT}/alloy/snmp-targets.yml" ]]; then
  echo '[]' > "${ROOT}/alloy/snmp-targets.yml"
fi

if [[ -n "${LIB:-}" && -d "${SRC}/.git" ]]; then
  git -C "${SRC}" checkout -- snmp/ || true
  info "restored ${SRC}/snmp to HEAD (library SoT is snmp-sd)"
fi

info "Built ${TAG}"
info ""
info "Pin in local/.env:"
info "  ALLOY_IMAGE=${TAG}"
info "  LAB_ALLOY_SNMP=1"
info ""
info "Discover (named auth + sysObjectID→module) then scrape:"
info "  make -C local alloy-snmp-discover"
info "  make -C local alloy-snmp-up"
