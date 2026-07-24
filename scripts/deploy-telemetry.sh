#!/usr/bin/env bash
# deploy-telemetry.sh — deploy the unified ktranslate telemetry stack to EKS.
#
# Same collector model as local/: ktranslate_snmp (poll+traps), flow, sFlow, syslog + gnmic + Alloy OTLP sink.
# See docs/ktranslate-unified-model.md
#
# Deploys:
#   - ktranslate-snmp, ktranslate-flow, ktranslate-sflow, ktranslate-syslog
#   - Alloy (OTLP forwarder), gnmic (gNMI)
#   - node telemetry Services (SNMP/gNMI DNAT targets)

set -euo pipefail

NAMESPACE="${1:-network-lab}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
K8S_DIR="${REPO_ROOT}/k8s"

info()  { echo "==> $*"; }
warn()  { echo "WARN: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

info "Checking prerequisites..."
kubectl cluster-info >/dev/null 2>&1 || fatal "kubectl is not configured. Run: aws eks update-kubeconfig ..."
kubectl get secret grafana-cloud-credentials -n "$NAMESPACE" >/dev/null 2>&1 || \
  fatal "grafana-cloud-credentials Secret not found. See k8s/telemetry/grafana-cloud-secret.yaml.example"

info "Applying node telemetry Services..."
kubectl apply -f "$K8S_DIR/telemetry/node-telemetry-services.yaml"

info "Deploying ktranslate stack (SNMP / flow / sFlow / syslog)..."
kubectl apply -f "$K8S_DIR/telemetry/ktranslate-config.yaml"
kubectl apply -f "$K8S_DIR/telemetry/ktranslate-snmp.yaml"
kubectl apply -f "$K8S_DIR/telemetry/ktranslate.yaml"
kubectl apply -f "$K8S_DIR/telemetry/ktranslate-sflow.yaml"
kubectl apply -f "$K8S_DIR/telemetry/ktranslate-syslog.yaml"

info "Deploying Alloy (OTLP forwarder)..."
kubectl apply -f "$K8S_DIR/telemetry/alloy-config.yaml"
kubectl apply -f "$K8S_DIR/telemetry/alloy.yaml"

info "Deploying gnmic..."
kubectl apply -f "$K8S_DIR/telemetry/gnmic-config.yaml"
kubectl apply -f "$K8S_DIR/telemetry/gnmic.yaml"

for dep in ktranslate-snmp ktranslate-flow ktranslate-sflow ktranslate-syslog alloy gnmic; do
  info "Waiting for ${dep}..."
  kubectl rollout status "deployment/${dep}" -n "$NAMESPACE" --timeout=180s
done

FLOW_IP=$(kubectl get svc ktranslate-flow -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "unknown")
SYSLOG_NODEPORT=$(kubectl get svc ktranslate-syslog -n "$NAMESPACE" -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "30614")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Unified ktranslate telemetry deployed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ktranslate-snmp    SNMP poll + traps (one container) → OTLP → Alloy"
echo " ktranslate-flow    NetFlow v9 at ${FLOW_IP}:9995 (softflowd on clients)"
echo " ktranslate-sflow   sFlow v5 at ktranslate-sflow:6343"
echo " ktranslate-syslog  syslog NodePort :${SYSLOG_NODEPORT} → UDP 1514"
echo " Alloy              OTLP :4317 → Grafana Cloud"
echo " gnmic              gNMI → Prometheus scrape → Alloy remote_write"
echo ""
echo " Verify SNMP:  count by (device_name) (kentik_snmp_DeviceMetrics)"
echo " Verify flow:  topk(20, network_io_by_flow_bytes)"
echo " Configure device syslog: kubectl apply -f k8s/telemetry/srl-syslog-config.yaml"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
