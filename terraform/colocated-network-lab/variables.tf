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

variable "public_subnet_ids" {
  description = "Public subnets for optional NetBox UI NLB (internet-facing). Empty = no public UI."
  type        = list(string)
  default     = []
}

variable "netbox_ui_cidrs" {
  description = "CIDRs allowed to reach NetBox UI :8000 via the public NLB (e.g. home /32). Empty disables public UI."
  type        = list(string)
  default     = []
}

variable "netbox_ui_allow_grafana_cloud" {
  description = "If true (lab), also allow 0.0.0.0/0 on :8000 so Grafana Cloud Infinity can reach the NetBox API. UI still requires login; API requires token."
  type        = bool
  default     = false
}

variable "instance_type" {
  description = "Lab host — HQ + 2 branches (5 SRL + 4 clients + k3s). ≥32 GB RAM recommended."
  type        = string
  default     = "m5.4xlarge"
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

variable "gc_otlp_url_2" {
  description = "Optional second Grafana Cloud OTLP endpoint (dual-ship)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "gc_otlp_account_2" {
  description = "Optional second Grafana Cloud OTLP instance ID"
  type        = string
  default     = ""
  sensitive   = true
}

variable "gc_otlp_key_2" {
  description = "Optional second Grafana Cloud OTLP token"
  type        = string
  default     = ""
  sensitive   = true
}
