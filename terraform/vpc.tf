module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = local.name
  cidr = "10.0.0.0/16"

  azs = local.azs

  # Public subnets for the bastion and NAT Gateway
  public_subnets = [for i, az in local.azs : cidrsubnet("10.0.0.0/16", 8, i)]

  # Private subnets for EKS nodes — offset by 10 to avoid overlap
  private_subnets = [for i, az in local.azs : cidrsubnet("10.0.0.0/16", 8, i + 10)]

  enable_nat_gateway   = true
  single_nat_gateway   = true  # One NAT GW keeps demo costs low
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Required tags for EKS subnet auto-discovery
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"                   = "1"
    "kubernetes.io/cluster/${local.name}"               = "owned"
  }
}
