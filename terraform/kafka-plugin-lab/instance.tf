resource "aws_instance" "lab_host" {
  count = local.lab_count

  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = var.private_subnet_id
  vpc_security_group_ids      = [aws_security_group.lab_host[0].id]
  iam_instance_profile        = aws_iam_instance_profile.lab_host[0].name
  user_data_replace_on_change = true
  associate_public_ip_address = false

  root_block_device {
    volume_size = var.root_volume_gb
    volume_type = "gp3"
  }

  user_data = base64encode(templatefile("${path.module}/userdata.sh.tpl", {
    plugin_repo   = var.plugin_repo
    plugin_branch = var.plugin_branch
  }))

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  tags = {
    Name = "${var.project_tag}-kafka-plugin-lab"
    role = "kafka-plugin-lab"
  }
}
