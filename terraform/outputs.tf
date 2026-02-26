output "bastion_public_ip" {
  description = "Public IP of the bastion host — SSH to this address using the generated .pem key"
  value       = aws_instance.bastion.public_ip
}

output "bastion_ssh_command" {
  description = "Ready-to-run SSH command to reach the bastion"
  value       = "ssh -i ../${local.name}.pem ec2-user@${aws_instance.bastion.public_ip}"
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS private API endpoint (only reachable from within the VPC)"
  value       = module.eks.cluster_endpoint
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (EKS nodes)"
  value       = module.vpc.private_subnets
}

output "public_subnet_ids" {
  description = "Public subnet IDs (bastion, NAT GW)"
  value       = module.vpc.public_subnets
}

output "next_steps" {
  description = "What to do after apply"
  value       = <<-EOT
    1. SSH to the bastion:
         ssh -i ../${local.name}.pem ec2-user@${aws_instance.bastion.public_ip}

    2. On the bastion, wait for kubectl to be configured (takes ~2 min after first boot):
         tail -f ~/kubectl-setup.log

    3. Verify cluster access:
         kubectl get nodes

    4. Run the access script locally to open port forwards:
         source ../scripts/setup-env.sh && ../scripts/access.sh
  EOT
}
