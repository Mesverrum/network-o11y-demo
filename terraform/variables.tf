variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-1"  # us-east-1 is at VPC limit; eu-west-1 has capacity
}

variable "cluster_name" {
  description = "Name used for the EKS cluster and all associated resources"
  type        = string
  default     = "network-o11y-demo"
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed inbound to the bastion on port 22 — set to your public IP (e.g. 1.2.3.4/32)"
  type        = string

  validation {
    condition     = can(cidrhost(var.allowed_ssh_cidr, 0))
    error_message = "allowed_ssh_cidr must be a valid CIDR block (e.g. 1.2.3.4/32)."
  }
}

variable "eks_version" {
  description = "Kubernetes version for the EKS cluster"
  type        = string
  default     = "1.31"
}

variable "eks_node_instance_type" {
  description = "EC2 instance type for EKS worker nodes. SR Linux containers are memory-heavy — m5.2xlarge (32 GB) minimum."
  type        = string
  default     = "m5.2xlarge"
}

variable "eks_node_desired_count" {
  description = "Desired number of EKS worker nodes"
  type        = number
  default     = 2
}

variable "eks_node_min_count" {
  description = "Minimum number of EKS worker nodes"
  type        = number
  default     = 1
}

variable "eks_node_max_count" {
  description = "Maximum number of EKS worker nodes"
  type        = number
  default     = 3
}
