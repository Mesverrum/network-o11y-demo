locals {
  subnet_az_pairs = [
    for sid in var.private_subnet_ids : {
      subnet_id = sid
      az        = data.aws_subnet.private[sid].availability_zone
    }
  ]
  # One host per private subnet (expect 2 AZs).
  traffic_hosts = var.lab_enabled ? local.subnet_az_pairs : []
}

resource "aws_instance" "traffic" {
  for_each = { for h in local.traffic_hosts : h.subnet_id => h }

  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = each.value.subnet_id
  vpc_security_group_ids = [aws_security_group.traffic[0].id]
  iam_instance_profile   = aws_iam_instance_profile.traffic[0].name
  user_data_replace_on_change = true

  user_data = base64encode(templatefile("${path.module}/traffic-userdata.sh.tpl", {
    region               = var.aws_region
    project_tag          = var.project_tag
    interval_sec         = var.traffic_interval_sec
    nlb_dns              = try(aws_lb.nlb[0].dns_name, "")
    hybrid_probe_enabled = var.hybrid_probe_enabled && var.gc_otlp_url != "" && var.gc_otlp_account != "" && var.gc_otlp_key != ""
    gc_otlp_url          = var.gc_otlp_url
    gc_otlp_account      = var.gc_otlp_account
    gc_otlp_key          = var.gc_otlp_key
    laptop_callback_url  = var.laptop_callback_url
    probe_s3_bucket      = try(aws_s3_bucket.probe_bundle[0].id, "")
  }))

  tags = {
    Name = "${var.project_tag}-traffic-${each.value.az}"
    role = "traffic-host"
  }

  depends_on = [aws_lb.nlb]
}

resource "aws_lb_target_group_attachment" "traffic" {
  for_each = aws_instance.traffic

  target_group_arn = aws_lb_target_group.traffic[0].arn
  target_id        = each.value.id
  port             = 8080
}
