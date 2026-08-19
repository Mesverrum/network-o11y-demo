resource "aws_lb" "nlb" {
  count              = local.lab_count
  name               = "${var.project_tag}-dash-nlb"
  internal           = true
  load_balancer_type = "network"
  subnets            = var.private_subnet_ids

  enable_cross_zone_load_balancing = true
}

resource "aws_lb_target_group" "traffic" {
  count       = local.lab_count
  name        = "${var.project_tag}-dash-tg"
  port        = 8080
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    enabled             = true
    protocol            = "TCP"
    port                = "8080"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 30
  }
}

resource "aws_lb_listener" "traffic" {
  count             = local.lab_count
  load_balancer_arn = aws_lb.nlb[0].arn
  port              = 8080
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.traffic[0].arn
  }
}
