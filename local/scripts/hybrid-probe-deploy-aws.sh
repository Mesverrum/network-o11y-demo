#!/usr/bin/env bash
# Deploy hybrid probe to AWS dashboard-lab EC2 hosts via SSM.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB="${ROOT}/terraform/aws-dashboard-lab"
PROBE="${ROOT}/local/hybrid-probe"
PROFILE="${AWS_PROFILE:-mvr}"
REGION="${AWS_REGION:-us-east-1}"
TF="${ROOT}/local/scripts/aws-lab-terraform.sh"

aws_cmd() {
  if command -v aws >/dev/null 2>&1; then aws "$@"; return; fi
  "/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe" "$@"
}

aws_cmd sts get-caller-identity --profile "$PROFILE" --region "$REGION" >/dev/null

IDS=$(bash "$TF" "$LAB" output -json traffic_instance_ids 2>/dev/null | python3 -c "import sys,json; print(' '.join(json.load(sys.stdin)))")
[[ -n "$IDS" ]] || { echo "No traffic instances — run make -C local aws-lab-up"; exit 1; }

# OTLP creds for agents (lab only — instances are private)
ENV_FILE="${ROOT}/local/.env"
OTLP_URL=$(grep -E '^GC_OTLP_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
OTLP_ACCT=$(grep -E '^GC_OTLP_ACCOUNT=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
OTLP_KEY=$(grep -E '^GC_OTLP_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')

B64_AGENT=$(base64 -w0 "$PROBE/agent.py")
B64_OTEL=$(base64 -w0 "$PROBE/otel_push.py")
B64_CFG=$(base64 -w0 "$PROBE/targets-aws.yaml")

read -r -d '' REMOTE_SCRIPT <<'EOS' || true
set -euo pipefail
mkdir -p /opt/hybrid-probe
echo "$B64_AGENT" | base64 -d >/opt/hybrid-probe/agent.py
echo "$B64_OTEL" | base64 -d >/opt/hybrid-probe/otel_push.py
echo "$B64_CFG" | base64 -d >/opt/hybrid-probe/targets-aws.yaml
cat >/opt/hybrid-probe/.env <<EOF
GC_OTLP_URL=$OTLP_URL
GC_OTLP_ACCOUNT=$OTLP_ACCT
GC_OTLP_KEY=$OTLP_KEY
EOF
dnf install -y python3 python3-pip >/dev/null
pip3 install -q pyyaml --ignore-scripts
cat >/etc/systemd/system/hybrid-probe.service <<'UNIT'
[Unit]
Description=Hybrid mesh probe agent
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/hybrid-probe
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /opt/hybrid-probe/agent.py --config /opt/hybrid-probe/targets-aws.yaml --listen 18080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now hybrid-probe.service
systemctl is-active hybrid-probe.service
EOS

# shellcheck disable=SC2016
REMOTE_SCRIPT="${REMOTE_SCRIPT//\$B64_AGENT/$B64_AGENT}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//\$B64_OTEL/$B64_OTEL}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//\$B64_CFG/$B64_CFG}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//\$OTLP_URL/$OTLP_URL}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//\$OTLP_ACCT/$OTLP_ACCT}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//\$OTLP_KEY/$OTLP_KEY}"

CMD_JSON=$(python3 -c "import json,sys; print(json.dumps([sys.stdin.read()]))" <<<"$REMOTE_SCRIPT")

CID=$(aws_cmd ssm send-command \
  --profile "$PROFILE" --region "$REGION" \
  --document-name AWS-RunShellScript \
  --instance-ids $IDS \
  --parameters "commands=${CMD_JSON}" \
  --query Command.CommandId --output text)

echo "SSM CommandId: $CID (waiting...)"
sleep 15
for i in $IDS; do
  echo "--- $i ---"
  aws_cmd ssm get-command-invocation --profile "$PROFILE" --region "$REGION" \
    --command-id "$CID" --instance-id "$i" \
    --query '{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' --output yaml
done
