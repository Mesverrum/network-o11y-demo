resource "aws_security_group" "traffic" {
  count       = local.lab_count
  name        = "${var.project_tag}-dashboard-lab-traffic"
  description = "Dashboard lab traffic generators + NLB targets"
  vpc_id      = var.vpc_id

  ingress {
    description = "NLB health checks and cross-AZ traffic"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.selected.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
