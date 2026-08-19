# Optional public NetBox UI via NLB (instance stays in private subnet).
# Enable with public_subnet_ids + netbox_ui_cidrs (e.g. your home /32).

locals {
  # Enable NLB when any CIDR is configured OR Grafana Cloud public access is requested.
  netbox_ui_ingress_cidrs = distinct(concat(
    var.netbox_ui_cidrs,
    var.netbox_ui_allow_grafana_cloud ? ["0.0.0.0/0"] : [],
  ))
  netbox_ui_enabled = local.lab_count > 0 && length(var.public_subnet_ids) > 0 && length(local.netbox_ui_ingress_cidrs) > 0
}

resource "aws_lb" "netbox_ui" {
  count = local.netbox_ui_enabled ? 1 : 0

  name               = "${var.project_tag}-netbox-ui"
  load_balancer_type = "network"
  internal           = false
  subnets            = var.public_subnet_ids

  tags = {
    Name = "${var.project_tag}-netbox-ui"
    role = "netbox-ui"
  }
}

resource "aws_lb_target_group" "netbox_ui" {
  count = local.netbox_ui_enabled ? 1 : 0

  name        = "${var.project_tag}-netbox-ui"
  port        = 8000
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    protocol            = "TCP"
    port                = "8000"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 30
  }

  tags = {
    Name = "${var.project_tag}-netbox-ui"
  }
}

resource "aws_lb_target_group_attachment" "netbox_ui" {
  count = local.netbox_ui_enabled ? 1 : 0

  target_group_arn = aws_lb_target_group.netbox_ui[0].arn
  target_id        = aws_instance.lab_host[0].id
  port             = 8000
}

resource "aws_lb_listener" "netbox_ui" {
  count = local.netbox_ui_enabled ? 1 : 0

  load_balancer_arn = aws_lb.netbox_ui[0].arn
  port              = 8000
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.netbox_ui[0].arn
  }
}
