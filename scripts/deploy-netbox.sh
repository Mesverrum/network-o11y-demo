#!/usr/bin/env bash
# deploy-netbox.sh — deploy NetBox and its supporting services to the EKS cluster.
#
# Deploys (all into the network-tools namespace):
#   1. netbox-credentials Secret  (from k8s/netbox/netbox-secret.yaml)
#   2. NetBox               via Helm chart (netbox-community/netbox-chart)
#   3. netbox-sd            Prometheus HTTP SD adapter (reads NetBox → Alloy)
#   4. netbox-populate Job  seeds NetBox with the SR Linux Clos fabric topology
#
# Prerequisites:
#   - kubectl is configured and pointing at the demo cluster.
#   - k8s/netbox/netbox-secret.yaml exists and has been filled in:
#       cp k8s/netbox/netbox-secret.yaml.example k8s/netbox/netbox-secret.yaml
#       # Edit — fill in superuser-password, superuser-api-token, secret-key,
#       #        and postgresql-password.
#       # NOTE: never commit this file (it is gitignored).
#
# Usage:
#   bash scripts/deploy-netbox.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
K8S_DIR="$REPO_ROOT/k8s"
NETBOX_DIR="$K8S_DIR/netbox"
NAMESPACE="network-tools"
CHART_VERSION="7.4.15"
CHART_REF="oci://ghcr.io/netbox-community/netbox-chart/netbox"

info()  { echo "==> $*"; }
warn()  { echo "WARN: $*" >&2; }
fatal() { echo "ERROR: $*" >&2; exit 1; }

# ─── Preflight ────────────────────────────────────────────────────────────────

info "Checking prerequisites..."

kubectl cluster-info >/dev/null 2>&1 \
  || fatal "kubectl is not configured. Run: aws eks update-kubeconfig ..."

[[ -f "$NETBOX_DIR/netbox-secret.yaml" ]] \
  || fatal "netbox-secret.yaml not found. Run:
  cp k8s/netbox/netbox-secret.yaml.example k8s/netbox/netbox-secret.yaml
  # Fill in all CHANGE_ME values, then re-run this script."

# ─── Namespace ───────────────────────────────────────────────────────────────

info "Ensuring namespace '$NAMESPACE' exists..."
kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 \
  || kubectl create namespace "$NAMESPACE"

# ─── Credentials Secret ───────────────────────────────────────────────────────

info "Applying netbox-credentials Secret..."
kubectl apply -f "$NETBOX_DIR/netbox-secret.yaml"

# ─── NetBox Helm install / upgrade ────────────────────────────────────────────

info "Installing/upgrading NetBox (chart $CHART_VERSION, NetBox v4.5.3)..."
info "  This pulls the chart from GHCR — first run may take a few minutes."

helm upgrade --install netbox "$CHART_REF" \
  --namespace "$NAMESPACE" \
  --version   "$CHART_VERSION" \
  --values    "$NETBOX_DIR/values.yaml" \
  --wait \
  --timeout   10m

info "NetBox pods:"
kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=netbox"

# ─── netbox-sd — Prometheus HTTP SD adapter ──────────────────────────────────

info "Deploying netbox-sd (Prometheus HTTP SD adapter)..."
kubectl apply -f "$NETBOX_DIR/netbox-sd.yaml"

info "Waiting for netbox-sd to be ready..."
kubectl rollout status deployment/netbox-sd -n "$NAMESPACE" --timeout=120s

# ─── Populate Job ─────────────────────────────────────────────────────────────

info "Deleting any previous populate job..."
kubectl delete job netbox-populate -n "$NAMESPACE" --ignore-not-found

info "Running NetBox populate job (seeds fabric topology)..."
kubectl apply -f "$NETBOX_DIR/populate-job.yaml"

info "Waiting for populate job to complete (up to 5 minutes)..."
kubectl wait \
  --for=condition=complete \
  --timeout=300s \
  job/netbox-populate \
  -n "$NAMESPACE"

info "Populate job logs:"
kubectl logs -n "$NAMESPACE" job/netbox-populate

# ─── Summary ─────────────────────────────────────────────────────────────────

NETBOX_IP=$(kubectl get svc netbox -n "$NAMESPACE" \
  -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "unknown")

SD_IP=$(kubectl get svc netbox-sd -n "$NAMESPACE" \
  -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "unknown")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " NetBox deployed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " NetBox UI    ClusterIP ${NETBOX_IP}:80"
echo "              (login: admin / see netbox-secret.yaml)"
echo ""
echo " netbox-sd    ClusterIP ${SD_IP}:8181"
echo "              Prometheus SD endpoint: /targets"
echo "              Queried by Grafana Alloy for enrichment labels"
echo ""
echo " To access NetBox UI via SSH tunnel, run locally:"
echo "   bash scripts/access.sh"
echo "   → http://localhost:8080"
echo ""
echo " To verify netbox-sd is working:"
echo "   kubectl port-forward -n network-tools svc/netbox-sd 8181:8181 &"
echo "   curl http://localhost:8181/targets | python3 -m json.tool"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
