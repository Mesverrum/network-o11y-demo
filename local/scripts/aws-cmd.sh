#!/usr/bin/env bash
# AWS CLI wrapper: native Linux aws, or Windows aws.exe via PowerShell (WSL on Windows host).
set -euo pipefail

aws_cmd() {
  local profile="${AWS_PROFILE:-}"
  if command -v aws >/dev/null 2>&1; then
    if [[ -n "$profile" ]]; then aws --profile "$profile" "$@"; else aws "$@"; fi
    return
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
    powershell.exe "${ps[@]}"
    return
  fi
  echo "ERROR: aws CLI not found (install awscli or use Windows AWSCLIV2)" >&2
  return 127
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  aws_cmd "$@"
fi
