variable "aws_region" {
  description = "AWS region for the dashboard lab"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile (SSO). Leave empty to use AWS_PROFILE / default chain."
  type        = string
  default     = "mvr"
}

variable "lab_enabled" {
  description = "When false, no billable lab resources are created (session tear-down)."
  type        = bool
  default     = true
}

variable "vpc_id" {
  description = "Existing lab VPC (must have private subnets + NAT for egress panels)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs in at least two AZs (cross-AZ traffic)."
  type        = list(string)
}

variable "instance_type" {
  description = "Traffic generator instance size"
  type        = string
  default     = "t3.micro"
}

variable "traffic_interval_sec" {
  description = "Sleep between traffic bursts on each host"
  type        = number
  default     = 30
}

variable "project_tag" {
  type    = string
  default = "network-o11y-demo"
}

variable "hybrid_probe_enabled" {
  description = "Deprecated: use Grafana Cloud Synthetic Monitoring (make synthetic-up). Custom hybrid-probe userdata install."
  type        = bool
  default     = false
}

variable "gc_otlp_url" {
  description = "Grafana Cloud OTLP endpoint (from local/.env)."
  type        = string
  default     = ""
  sensitive   = true
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

variable "laptop_callback_url" {
  description = "Optional http://PUBLIC_IP:18080/health for AWS→laptop mesh probes."
  type        = string
  default     = ""
}
