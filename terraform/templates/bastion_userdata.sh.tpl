#!/bin/bash
set -euo pipefail

LOG=/home/ec2-user/kubectl-setup.log
echo "$(date -u) user_data started" > "$LOG"

# Install kubectl matching cluster minor version
# NOTE: $( ) is bash command substitution and passes through Terraform unchanged.
# ${cluster_name} and ${aws_region} are substituted by Terraform at plan time.
curl -sLO "https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl"
chmod +x kubectl
mv kubectl /usr/local/bin/kubectl
echo "$(date -u) kubectl installed: $(kubectl version --client --short 2>/dev/null)" >> "$LOG"

# Wait for EKS cluster to become ACTIVE (it may still be initialising at boot)
echo "$(date -u) Waiting for EKS cluster '${cluster_name}' to become ACTIVE..." >> "$LOG"
until aws eks describe-cluster \
        --name "${cluster_name}" \
        --region "${aws_region}" \
        --query "cluster.status" \
        --output text 2>/dev/null | grep -q "^ACTIVE$"; do
  echo "$(date -u) ... still waiting" >> "$LOG"
  sleep 30
done

# Configure kubeconfig for ec2-user
mkdir -p /home/ec2-user/.kube
aws eks update-kubeconfig \
  --name "${cluster_name}" \
  --region "${aws_region}" \
  --kubeconfig /home/ec2-user/.kube/config

chown -R ec2-user:ec2-user /home/ec2-user/.kube
echo "$(date -u) kubectl configured successfully for cluster: ${cluster_name}" >> "$LOG"
chown ec2-user:ec2-user "$LOG"
