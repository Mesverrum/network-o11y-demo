resource "aws_security_group" "lab_host" {
  count       = local.lab_count
  name        = "${var.project_tag}-kafka-plugin-lab"
  description = "Self-hosted Grafana + Kafka for unsigned plugin validation"
  vpc_id      = var.vpc_id

  ingress {
    description = "Grafana UI from VPC (SSM port-forward / jump)"
    from_port   = 3000
    to_port     = 3000
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
