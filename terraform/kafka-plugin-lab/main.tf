provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      project     = var.project_tag
      managed_by  = "terraform"
      component   = "kafka-plugin-lab"
      auto_delete = "true"
    }
  }
}

locals {
  lab_count = var.lab_enabled ? 1 : 0
}

data "aws_vpc" "selected" {
  id = var.vpc_id
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
