resource "aws_security_group" "lab_host" {
  count       = local.lab_count
  name        = "${var.project_tag}-colocated-network-lab"
  description = "Colocated ContainerLab + k3s ktranslate-golden (SSM; OTLP egress; optional NetBox UI)"
  vpc_id      = var.vpc_id

  # NetBox UI via public NLB (client IP preserved).
  # - netbox_ui_cidrs: operator home/office
  # - netbox_ui_allow_grafana_cloud: 0.0.0.0/0 for Grafana Cloud Infinity (lab)
  dynamic "ingress" {
    for_each = length(local.netbox_ui_ingress_cidrs) > 0 ? [1] : []
    content {
      description = "NetBox UI (TCP 8000) from allowed CIDRs"
      from_port   = 8000
      to_port     = 8000
      protocol    = "tcp"
      cidr_blocks = local.netbox_ui_ingress_cidrs
    }
  }

  # NLB health checks originate from within the VPC.
  dynamic "ingress" {
    for_each = length(local.netbox_ui_ingress_cidrs) > 0 ? [1] : []
    content {
      description = "NetBox UI health checks from VPC"
      from_port   = 8000
      to_port     = 8000
      protocol    = "tcp"
      cidr_blocks = [data.aws_vpc.selected.cidr_block]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_tag}-colocated-network-lab"
  }
}
