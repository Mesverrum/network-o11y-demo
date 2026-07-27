#!/usr/bin/env bash
# build-ktranslate-dev-image.sh — build local ktranslate with OTLP CHF fix (flow_only).
#
# Overlays a patched binary onto quay.io/kentik/ktranslate:latest.
# Source: Mesverrum/ktranslate branch fix/otel-chf-flow-only (pending kentik/ktranslate PR).
#
# Usage:
#   ./scripts/build-ktranslate-dev-image.sh
#   KTRANSLATE_SRC=~/projects/ktranslate ./scripts/build-ktranslate-dev-image.sh
#
# Then in local/.env:
#   KTRANSLATE_IMAGE=srl-local/ktranslate:otel-chf-dev
# Recreate collectors:
#   make -C local ktranslate-dev-recreate

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCKERFILE="${ROOT}/docker/ktranslate-dev/Dockerfile"
TAG="${KTRANSLATE_DEV_TAG:-srl-local/ktranslate:otel-chf-dev}"
REPO="${KTRANSLATE_REPO:-https://github.com/Mesverrum/ktranslate.git}"
BRANCH="${KTRANSLATE_BRANCH:-fix/otel-chf-flow-only}"
CLEANUP_SRC=""

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

command -v docker >/dev/null || die "docker required"

SRC="${KTRANSLATE_SRC:-}"
if [[ -z "$SRC" ]]; then
  if [[ -d /tmp/ktranslate/.git ]] && git -C /tmp/ktranslate rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
    SRC=/tmp/ktranslate
    info "Using existing clone: ${SRC} (${BRANCH})"
    git -C "$SRC" fetch origin "$BRANCH" 2>/dev/null || true
    git -C "$SRC" checkout "$BRANCH" 2>/dev/null || true
    git -C "$SRC" pull --ff-only origin "$BRANCH" 2>/dev/null || true
  else
    SRC="$(mktemp -d)"
    CLEANUP_SRC=1
    info "Cloning ${REPO} branch ${BRANCH} → ${SRC}"
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$SRC"
  fi
fi

[[ -f "${SRC}/cmd/ktranslate/main.go" ]] || die "not a ktranslate checkout: ${SRC}"
[[ -f "$DOCKERFILE" ]] || die "missing Dockerfile: ${DOCKERFILE}"

# Apply CHF/otel patches (idempotent).
python3 "${ROOT}/scripts/patch-ktranslate-chf-otel.py" "$SRC" \
  || die "CHF patch failed — set KTRANSLATE_SRC to a patched checkout"

info "Building ${TAG} (base quay.io/kentik/ktranslate:latest)..."
docker build \
  -f "$DOCKERFILE" \
  -t "$TAG" \
  "$SRC"

if [[ -n "$CLEANUP_SRC" ]]; then
  rm -rf "$SRC"
fi

info "Built ${TAG}"
info ""
info "Pin in local/.env:"
info "  KTRANSLATE_IMAGE=${TAG}"
info ""
info "Recreate ktranslate containers:"
info "  make -C local ktranslate-dev-recreate"
info ""
info "Verify CHF OTLP (after ~60s):"
info "  docker logs ktranslate_flow 2>&1 | grep 'Creating otel export.*chf.kkc'"
info "  # PromQL: count by (service_name) (kentik_ktranslate_chf_kkc_jchfq)"
