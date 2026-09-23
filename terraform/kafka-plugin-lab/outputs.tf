output "instance_id" {
  value = try(aws_instance.lab_host[0].id, null)
}

output "private_ip" {
  value = try(aws_instance.lab_host[0].private_ip, null)
}

output "ssm_port_forward" {
  value = try(
    "aws ssm start-session --target ${aws_instance.lab_host[0].id} --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000",
    null
  )
}
