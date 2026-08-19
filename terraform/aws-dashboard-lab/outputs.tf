output "lab_enabled" {
  value = var.lab_enabled
}

output "vpc_id" {
  value = var.vpc_id
}

output "nlb_dns_name" {
  value = try(aws_lb.nlb[0].dns_name, null)
}

output "nlb_arn" {
  value = try(aws_lb.nlb[0].arn, null)
}

output "traffic_instance_ids" {
  value = [for i in aws_instance.traffic : i.id]
}

output "traffic_private_ips" {
  value = { for k, i in aws_instance.traffic : k => i.private_ip }
}
