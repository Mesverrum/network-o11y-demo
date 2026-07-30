resource "aws_security_group" "lab_host" {
  count       = local.lab_count
  name        = "${var.project_tag}-colocated-network-lab"
  description = "Colocated ContainerLab + k3s ktranslate-golden (SSM; OTLP egress)"
  vpc_id      = var.vpc_id

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
