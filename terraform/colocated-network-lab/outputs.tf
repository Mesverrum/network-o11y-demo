output "account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "instance_id" {
  value = try(aws_instance.lab_host[0].id, null)
}

output "private_ip" {
  value = try(aws_instance.lab_host[0].private_ip, null)
}

output "netbox_ui_url" {
  description = "Public NetBox UI (NLB) when netbox_ui_cidrs + public_subnet_ids are set"
  value       = try("http://${aws_lb.netbox_ui[0].dns_name}:8000/", null)
}

output "ssm_connect_command" {
  value = try(
    "aws ssm start-session --target ${aws_instance.lab_host[0].id} --region ${var.aws_region}",
    null
  )
}

output "status_command" {
  value = try(
    "aws ssm send-command --instance-ids ${aws_instance.lab_host[0].id} --document-name AWS-RunShellScript --parameters commands='sudo journalctl -u network-o11y-telemetry -n 40 --no-pager' --region ${var.aws_region}",
    null
  )
}

output "grafana_checks" {
  value = <<-EOT
    PromQL (deployment_host="${var.ktrans_host}" or tester_id="${var.lab_tester_id}"):
      count by (device_name) (kentik_snmp_CPU)
      count(network_io_by_flow_bytes)
      kubectl get pods -n network-lab
  EOT
}
