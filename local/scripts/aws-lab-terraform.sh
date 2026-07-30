#!/usr/bin/env bash
# Terraform wrapper: native binary or Docker (Windows-friendly).
set -euo pipefail

LAB_DIR="${1:?lab dir required}"
shift
REPO_ROOT="$(cd "$(dirname "$LAB_DIR")/.." && pwd)"

PROFILE="${AWS_PROFILE:-mvr}"
AWS_DIR="${AWS_CONFIG_DIR:-}"

if [[ -z "$AWS_DIR" ]]; then
  if [[ -d "$HOME/.aws" ]]; then
    AWS_DIR="$HOME/.aws"
  elif [[ -d "/mnt/c/Users/${USER}/.aws" ]]; then
    AWS_DIR="/mnt/c/Users/${USER}/.aws"
  elif [[ -d "/mnt/c/Users/mesve/.aws" ]]; then
    AWS_DIR="/mnt/c/Users/mesve/.aws"
  fi
fi

if command -v terraform >/dev/null 2>&1; then
  exec terraform -chdir="$LAB_DIR" "$@"
fi

[[ -n "$AWS_DIR" && -d "$AWS_DIR" ]] || {
  echo "ERROR: terraform not found and AWS_DIR not set for Docker fallback" >&2
  exit 1
}

LAB_REL="${LAB_DIR#${REPO_ROOT}/}"

docker run --rm -i \
  -v "${REPO_ROOT}:/repo" -w "/repo/${LAB_REL}" \
  -v "${AWS_DIR}:/root/.aws:ro" \
  -e AWS_PROFILE="${PROFILE}" \
  -e AWS_SDK_LOAD_CONFIG=1 \
  hashicorp/terraform:1.9 \
  "$@"
