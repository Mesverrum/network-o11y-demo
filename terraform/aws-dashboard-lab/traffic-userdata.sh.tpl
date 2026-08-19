#!/bin/bash
# dashboard-lab traffic host bootstrap (rev 3)
set -euo pipefail
REGION="${region}"
PROJECT_TAG="${project_tag}"
INTERVAL="${interval_sec}"
NLB_DNS="${nlb_dns}"

dnf install -y curl awscli >/dev/null

cat >/usr/local/bin/o11y-traffic.sh <<'SCRIPT'
#!/bin/bash
set -uo pipefail
REGION="__REGION__"
PROJECT_TAG="__PROJECT_TAG__"
INTERVAL=__INTERVAL__
NLB_DNS="__NLB_DNS__"

log() { echo "$(date -Is) $*"; }

peer_ip() {
  aws ec2 describe-instances \
    --region "$REGION" \
    --filters "Name=tag:project,Values=$PROJECT_TAG" "Name=tag:component,Values=aws-dashboard-lab" "Name=tag:role,Values=traffic-host" "Name=instance-state-name,Values=running" \
    --query "Reservations[].Instances[?PrivateIpAddress!=null].[PrivateIpAddress,InstanceId]" \
    --output text | awk -v self="$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)" '$1 != self {print $1; exit}'
}

while true; do
  log "burst start"
  curl -fsS -m 5 -o /dev/null https://aws.amazon.com || log "internet curl failed"
  peer="$(peer_ip || true)"
  if [[ -n "$${peer:-}" ]]; then
    curl -fsS -m 3 -o /dev/null "http://$${peer}:8080/health" || log "peer curl failed ($peer)"
  fi
  if [[ -n "$NLB_DNS" ]]; then
    curl -fsS -m 3 -o /dev/null "http://$${NLB_DNS}:8080/health" || log "nlb curl failed"
  fi
  log "burst done; sleep $${INTERVAL}s"
  sleep "$INTERVAL"
done
SCRIPT

sed -i "s|__REGION__|$${REGION}|g" /usr/local/bin/o11y-traffic.sh
sed -i "s|__PROJECT_TAG__|$${PROJECT_TAG}|g" /usr/local/bin/o11y-traffic.sh
sed -i "s|__INTERVAL__|$${INTERVAL}|g" /usr/local/bin/o11y-traffic.sh
sed -i "s|__NLB_DNS__|$${NLB_DNS}|g" /usr/local/bin/o11y-traffic.sh
chmod +x /usr/local/bin/o11y-traffic.sh

cat >/usr/local/bin/o11y-http-server.sh <<'HTTP'
#!/bin/bash
cd /var/tmp
exec python3 -m http.server 8080
HTTP
chmod +x /usr/local/bin/o11y-http-server.sh

cat >/etc/systemd/system/o11y-http.service <<'UNIT'
[Unit]
Description=Dashboard lab HTTP target
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/o11y-http-server.sh
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/o11y-traffic.service <<'UNIT'
[Unit]
Description=Dashboard lab traffic generator
After=network-online.target o11y-http.service

[Service]
Type=simple
ExecStart=/usr/local/bin/o11y-traffic.sh
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now o11y-http.service o11y-traffic.service

# SSM agent (for optional post-deploy SSM commands)
dnf install -y amazon-ssm-agent >/dev/null 2>&1 || true
systemctl enable --now amazon-ssm-agent 2>/dev/null || true

%{ if hybrid_probe_enabled }
# Hybrid mesh probe → Grafana Cloud OTLP (bundle from S3; userdata size limit)
mkdir -p /opt/hybrid-probe
cat >/opt/hybrid-probe/.env <<'OTLP'
GC_OTLP_URL=${gc_otlp_url}
GC_OTLP_ACCOUNT=${gc_otlp_account}
GC_OTLP_KEY=${gc_otlp_key}
OTLP
aws s3 sync "s3://${probe_s3_bucket}/hybrid-probe/" /opt/hybrid-probe/ --region "${region}" || true
for i in 1 2 3 4 5 6 7 8 9 10; do
  aws s3 sync "s3://${probe_s3_bucket}/hybrid-probe/" /opt/hybrid-probe/ --region "${region}" && break
  sleep 10
done
test -f /opt/hybrid-probe/agent.py
%{ if laptop_callback_url != "" }
cat >>/opt/hybrid-probe/targets-aws.yaml <<'LAPTOP'
  - name: laptop-callback
    url: ${laptop_callback_url}
    type: laptop
    direction: aws_to_laptop
LAPTOP
%{ endif }
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
%{ endif }
