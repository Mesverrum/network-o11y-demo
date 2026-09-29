# Public NLB listener for the lab circuit-fault webhook (Grafana Cloud + browser actions).
# Enable with the same public_subnet_ids + CIDRs as the NetBox UI NLB.
# provision-lab-circuit-fault.py also creates these via AWS CLI if they are missing.

resource "aws_lb_target_group" "lab_fault" {
  count = local.netbox_ui_enabled ? 1 : 0

  name        = "${var.project_tag}-lab-fault"
  port        = 8788
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    protocol            = "TCP"
    port                = "8788"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 30
  }

  tags = {
    Name = "${var.project_tag}-lab-fault"
    role = "lab-fault-webhook"
  }
}

resource "aws_lb_target_group_attachment" "lab_fault" {
  count = local.netbox_ui_enabled ? 1 : 0

  target_group_arn = aws_lb_target_group.lab_fault[0].arn
  target_id        = aws_instance.lab_host[0].id
  port             = 8788
}

resource "aws_lb_listener" "lab_fault" {
  count = local.netbox_ui_enabled ? 1 : 0

  load_balancer_arn = aws_lb.netbox_ui[0].arn
  port              = 8788
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.lab_fault[0].arn
  }
}
