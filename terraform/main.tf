provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project    = "network-o11y-demo"
      managed_by = "terraform"
    }
  }
}

locals {
  name = var.cluster_name
  # Use 2 AZs — enough for HA at demo cost
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}
