provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      project    = var.project_tag
      managed_by = "terraform"
      component  = "aws-dashboard-lab"
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

data "aws_subnet" "private" {
  for_each = toset(var.private_subnet_ids)
  id       = each.value
}
