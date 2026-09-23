#!/usr/bin/env bash
set -euo pipefail
WIN_LAB="/mnt/c/Users/mesve/projects/network-o11y-demo/terraform/kafka-plugin-lab"
WSL_ROOT="${HOME}/network-o11y-demo"
LAB="${WSL_ROOT}/terraform/kafka-plugin-lab"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"

mkdir -p "${WSL_ROOT}/terraform"
rm -rf "$LAB"
cp -a "$WIN_LAB" "$LAB"

if [[ -z "${AWS_ACCESS_KEY_ID:-}" || -z "${AWS_SECRET_ACCESS_KEY:-}" || -z "${AWS_SESSION_TOKEN:-}" ]]; then
  if command -v aws >/dev/null 2>&1; then
    eval "$(aws --profile "$PROFILE" configure export-credentials --format env | tr -d '\r')"
  else
    echo "ERROR: export AWS session credentials first; on Windows use the PowerShell wrapper pattern from kafka-plugin-lab-up.ps1" >&2
    exit 1
  fi
fi
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION" AWS_PROFILE="" AWS_SDK_LOAD_CONFIG=0

docker run --rm \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
  -e AWS_REGION -e AWS_DEFAULT_REGION -e AWS_PROFILE= -e AWS_SDK_LOAD_CONFIG=0 \
  -v "${WSL_ROOT}:/repo" -w /repo/terraform/kafka-plugin-lab \
  hashicorp/terraform:1.9 \
  destroy -auto-approve -input=false -var=aws_profile= -var=lab_enabled=true
