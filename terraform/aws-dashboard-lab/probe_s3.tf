# Probe bundle for traffic hosts (userdata stays under 16 KiB).
locals {
  probe_files = var.hybrid_probe_enabled && var.gc_otlp_url != "" ? {
    "agent.py"          = "${path.module}/../../local/hybrid-probe/agent.py"
    "otel_push.py"      = "${path.module}/../../local/hybrid-probe/otel_push.py"
    "targets-aws.yaml"  = "${path.module}/../../local/hybrid-probe/targets-aws.yaml"
  } : {}
}

resource "aws_s3_bucket" "probe_bundle" {
  count  = length(local.probe_files) > 0 ? 1 : 0
  bucket = "${var.project_tag}-dash-lab-probe-${data.aws_caller_identity.current.account_id}"
  tags   = { project = var.project_tag, component = "aws-dashboard-lab" }
}

resource "aws_s3_bucket_versioning" "probe_bundle" {
  count  = length(local.probe_files) > 0 ? 1 : 0
  bucket = aws_s3_bucket.probe_bundle[0].id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_object" "probe_file" {
  for_each = local.probe_files

  bucket = aws_s3_bucket.probe_bundle[0].id
  key    = "hybrid-probe/${each.key}"
  source = each.value
  etag   = filemd5(each.value)
}
