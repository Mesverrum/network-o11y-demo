# ─── EKS Cluster ──────────────────────────────────────────────────────────────

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.name
  cluster_version = var.eks_version

  # Private endpoint only — all kubectl access goes through the bastion
  cluster_endpoint_private_access = true
  cluster_endpoint_public_access  = false

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Allow the Terraform caller to administer the cluster during apply
  enable_cluster_creator_admin_permissions = true

  # Allow the bastion to reach the private EKS API endpoint on port 443
  cluster_security_group_additional_rules = {
    ingress_from_bastion = {
      description              = "Allow bastion to access the EKS API"
      protocol                 = "tcp"
      from_port                = 443
      to_port                  = 443
      type                     = "ingress"
      source_security_group_id = aws_security_group.bastion.id
    }
  }

  cluster_addons = {
    coredns    = { most_recent = true }
    kube-proxy = { most_recent = true }
    vpc-cni    = { most_recent = true }
  }

  # Allow all UDP between worker nodes so Clabbernetes VxLAN tunnels (UDP 14789)
  # can carry SR Linux inter-node links across different Availability Zones.
  node_security_group_additional_rules = {
    ingress_udp_self = {
      description = "Allow all UDP between nodes for VxLAN inter-pod links"
      protocol    = "udp"
      from_port   = 1
      to_port     = 65535
      type        = "ingress"
      self        = true
    }
  }

  eks_managed_node_groups = {
    main = {
      name           = "${local.name}-nodes"
      instance_types = [var.eks_node_instance_type]

      min_size     = var.eks_node_min_count
      max_size     = var.eks_node_max_count
      desired_size = var.eks_node_desired_count

      # Explicit IAM role name avoids the 38-char name_prefix limit
      iam_role_name            = "${local.name}-ng-role"
      iam_role_use_name_prefix = false

      # SR Linux images are ~1.3 GiB each; 100 GiB provides headroom for
      # pulling 4-5 images per node without hitting disk pressure.
      disk_size = 100
    }
  }
}

# ─── Bastion → EKS Access Entry ───────────────────────────────────────────────
# Grant the bastion's IAM role cluster-admin so it can run kubectl port-forward.

resource "aws_eks_access_entry" "bastion" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.bastion.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "bastion" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.bastion.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}
