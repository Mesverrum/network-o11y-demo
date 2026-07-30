variable "aws_region" {
  description = "AWS region for the colocated lab host"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile (SSO). Leave empty to use AWS_PROFILE / default chain."
  type        = string
  default     = ""
}

variable "lab_enabled" {
  description = "When false, no billable lab resources are created."
  type        = bool
  default     = true
}

variable "vpc_id" {
  description = "Existing VPC with NAT egress (for OTLP to Grafana Cloud)."
  type        = string
}

variable "private_subnet_id" {
  description = "Private subnet for the lab host (needs NAT route)."
  type        = string
}

variable "instance_type" {
  description = "Lab host — ContainerLab fabric + k3s collectors (≥16 GB RAM)"
  type        = string
  default     = "m5.2xlarge"
}

variable "root_volume_gb" {
  type    = number
  default = 120
}

variable "project_tag" {
  type    = string
  default = "network-o11y-demo"
}

variable "repo_url" {
  type    = string
  default = "https://github.com/Mesverrum/network-o11y-demo.git"
}

variable "repo_branch" {
  type    = string
  default = "main"
}

variable "ktrans_host" {
  description = "deployment.host / OTEL service.name suffix"
  type        = string
  default     = "aws-colocated-lab"
}

variable "lab_tester_id" {
  description = "topology/entity tester_id label in Grafana"
  type        = string
  default     = "aws-colocated-lab"
}

variable "gc_otlp_url" {
  type      = string
  default   = ""
  sensitive = true
}

variable "gc_otlp_account" {
  type      = string
  default   = ""
  sensitive = true
}

variable "gc_otlp_key" {
  type      = string
  default   = ""
  sensitive = true
}
