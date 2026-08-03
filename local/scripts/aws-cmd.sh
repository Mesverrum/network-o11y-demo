#!/usr/bin/env bash
# AWS CLI wrapper: native Linux aws, Windows aws.exe (WSL), PowerShell, or Docker aws-cli.
set -euo pipefail

aws_cmd() {
  local profile="${AWS_PROFILE:-}"
  local -a cmd
  local aws_dir="${AWS_CONFIG_DIR:-}"

  if [[ -z "$aws_dir" ]]; then
    if [[ -d "${HOME}/.aws" ]]; then
      aws_dir="${HOME}/.aws"
    elif [[ -d "/mnt/c/Users/${USER}/.aws" ]]; then
      aws_dir="/mnt/c/Users/${USER}/.aws"
    elif [[ -d "/mnt/c/Users/mesve/.aws" ]]; then
      aws_dir="/mnt/c/Users/mesve/.aws"
    fi
  fi

  if command -v aws >/dev/null 2>&1; then
    cmd=(aws)
    [[ -n "$profile" ]] && cmd+=(--profile "$profile")
    cmd+=("$@")
    "${cmd[@]}" 2>/dev/null && return 0
  fi

  local win_aws="/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe"
  if [[ -f "$win_aws" ]]; then
    cmd=("$win_aws")
    [[ -n "$profile" ]] && cmd+=(--profile "$profile")
    cmd+=("$@")
    "${cmd[@]}" 2>/dev/null && return 0
  fi

  if command -v powershell.exe >/dev/null 2>&1; then
    local -a ps=(-NoProfile -Command)
    local inner="& 'C:/Program Files/Amazon/AWSCLIV2/aws.exe'"
    if [[ -n "$profile" ]]; then
      inner+=" --profile '$profile'"
    fi
    local arg
    for arg in "$@"; do
      arg="${arg//\'/\'\'}"
      inner+=" '$arg'"
    done
    ps+=("$inner")
    powershell.exe "${ps[@]}" 2>/dev/null && return 0
  fi

  if command -v docker >/dev/null 2>&1 && [[ -n "$aws_dir" && -d "$aws_dir" ]]; then
    docker run --rm \
      -v "${aws_dir}:/root/.aws:ro" \
      -e "AWS_PROFILE=${profile}" \
      -e AWS_SDK_LOAD_CONFIG=1 \
      amazon/aws-cli:2.15.49 \
      "$@" && return 0
  fi

  echo "ERROR: aws CLI not found (install awscli, Windows AWSCLIV2, or Docker)" >&2
  return 127
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  aws_cmd "$@"
fi
