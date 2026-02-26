#!/usr/bin/env bash
# deploy-telemetry.sh — deploy the full telemetry stack to the EKS cluster.
#
# Deploys:
#   - ktranslate   — NetFlow v9 receiver (from softflowd on client nodes) → OTLP → Alloy
#   - Alloy        — SNMP poller + OTLP pipeline → Grafana Cloud
#   - gnmic        — gNMI streaming subscriber → Prometheus → Alloy
#   - Telemetry Services — ClusterIP Services for SNMP/gNMI per SR Linux node
#
# Note on flow data: SR Linux in containerized/simulator mode only produces sFlow
# counter-sample datagrams (device statistics), NOT flow-sample records. Flow data
# therefore comes from softflowd running on the Linux client nodes — managed
# automatically by the network-reconciler.
#
# Prerequisites:
#   1. kubectl is configured and pointing at the demo cluster.
#   2. The topology is deployed and networking fixes are applied:
#        kubectl apply -f k8s/topology/manifests.yaml
#        bash scripts/fix-networking.sh
#        kubectl apply -f k8s/network-reconciler.yaml
#   3. Grafana Cloud credentials Secret exists:
#        cp k8s/telemetry/grafana-cloud-secret.yaml.example k8s/telemetry/grafana-cloud-secret.yaml
#        # Fill in OTLP_ENDPOINT, PROM_URL, INSTANCE_ID, API_TOKEN
#        kubectl apply -f k8s/telemetry/grafana-cloud-secret.yaml

set -euo pipefail

NAMESPACE="${1:-network-lab}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")/k8s"

info()  { echo "==> $*"; }
warn()  { echo "WARN: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

# ─── Preflight checks ─────────────────────────────────────────────────────────

info "Checking prerequisites..."

kubectl cluster-info >/dev/null 2>&1 || fatal "kubectl is not configured. Run: aws eks update-kubeconfig ..."

kubectl get secret grafana-cloud-credentials -n "$NAMESPACE" >/dev/null 2>&1 || \
  fatal "grafana-cloud-credentials Secret not found. See k8s/telemetry/grafana-cloud-secret.yaml.example"

# ─── Deploy telemetry manifests ───────────────────────────────────────────────

info "Applying node telemetry Services (SNMP UDP 161, gNMI TCP 57400)..."
kubectl apply -f "$K8S_DIR/telemetry/node-telemetry-services.yaml"

info "Deploying ktranslate (NetFlow v9 receiver)..."
kubectl apply -f "$K8S_DIR/telemetry/ktranslate.yaml"

info "Deploying Alloy (SNMP + OTLP → Grafana Cloud)..."
kubectl apply -f "$K8S_DIR/telemetry/alloy-config.yaml"
kubectl apply -f "$K8S_DIR/telemetry/alloy.yaml"

info "Deploying gnmic (gNMI → Prometheus)..."
kubectl apply -f "$K8S_DIR/telemetry/gnmic-config.yaml"
kubectl apply -f "$K8S_DIR/telemetry/gnmic.yaml"

# ─── Wait for deployments to become ready ─────────────────────────────────────

info "Waiting for ktranslate..."
kubectl rollout status deployment/ktranslate -n "$NAMESPACE" --timeout=120s

info "Waiting for Alloy..."
kubectl rollout status deployment/alloy -n "$NAMESPACE" --timeout=120s

info "Waiting for gnmic..."
kubectl rollout status deployment/gnmic -n "$NAMESPACE" --timeout=120s

# ─── Summary ──────────────────────────────────────────────────────────────────

KTRANSLATE_IP=$(kubectl get svc ktranslate -n "$NAMESPACE" \
  -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "unknown")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Telemetry stack deployed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ktranslate   NetFlow v9 listener at ${KTRANSLATE_IP}:6343 (UDP)"
echo "              (receives from softflowd on client1/2/3 — managed by reconciler)"
echo " Alloy        OTLP receiver on :4317, SNMP polling on *-telemetry services"
echo " gnmic        gNMI → Prometheus on :9273"
echo ""
echo " To access Alloy UI via SSH tunnel:"
echo "   kubectl port-forward -n network-lab svc/alloy 12345:12345"
echo "   open http://localhost:12345"
echo ""
echo " To verify NetFlow v9 is arriving at ktranslate:"
echo "   kubectl logs -n network-lab deployment/ktranslate --follow"
echo ""
echo " To verify gnmic is streaming:"
echo "   kubectl logs -n network-lab deployment/gnmic --follow"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
