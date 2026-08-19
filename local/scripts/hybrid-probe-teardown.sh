#!/usr/bin/env bash
# Stop custom hybrid-probe agents (script-based mesh probes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"

echo "Stopping laptop/WSL hybrid-probe..."
pkill -f 'hybrid-probe/agent.py' 2>/dev/null || true

if command -v aws >/dev/null 2>&1; then
  AWS=aws
elif [[ -x "/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe" ]]; then
  AWS="/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe"
else
  AWS=""
fi

if [[ -n "$AWS" ]]; then
  IID="$("$AWS" --profile "$PROFILE" --region "$REGION" ec2 describe-instances \
    --filters "Name=tag:Name,Values=network-o11y-demo-colocated-lab" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)"
  if [[ -n "$IID" && "$IID" != "None" ]]; then
    echo "Tearing down hybrid-probe on colocated EC2 ($IID)..."
    CID="$("$AWS" --profile "$PROFILE" --region "$REGION" ssm send-command \
      --instance-ids "$IID" \
      --document-name AWS-RunShellScript \
      --parameters 'commands=["systemctl stop hybrid-probe.service 2>/dev/null || true","systemctl disable hybrid-probe.service 2>/dev/null || true","rm -f /etc/systemd/system/hybrid-probe.service","systemctl daemon-reload","rm -rf /opt/hybrid-probe","echo hybrid-probe-removed"]' \
      --query Command.CommandId --output text)"
    echo "SSM CommandId: $CID"
  fi
fi

echo "Custom hybrid-probe teardown complete."
