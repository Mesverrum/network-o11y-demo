provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      project     = var.project_tag
      managed_by  = "terraform"
      component   = "colocated-network-lab"
      persistence = "demo"
    }
  }
}

locals {
  lab_count = var.lab_enabled ? 1 : 0
}

data "aws_vpc" "selected" {
  id = var.vpc_id
}

data "aws_subnet" "private" {
  id = var.private_subnet_id
}
