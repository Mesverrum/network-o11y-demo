variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  description = "Leave empty when passing exported session creds into Terraform in Docker."
  type        = string
  default     = ""
}

variable "lab_enabled" {
  type    = bool
  default = true
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_id" {
  type = string
}

variable "instance_type" {
  type    = string
  default = "t3.xlarge"
}

variable "root_volume_gb" {
  type    = number
  default = 40
}

variable "project_tag" {
  type    = string
  default = "network-o11y-demo"
}

variable "plugin_repo" {
  type    = string
  default = "https://github.com/Mesverrum/grafana-kafka-datasource.git"
}

variable "plugin_branch" {
  type    = string
  default = "feat/enable-grafana-alerting"
}
