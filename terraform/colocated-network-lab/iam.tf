resource "aws_iam_role" "lab_host" {
  count = local.lab_count
  name  = "${var.project_tag}-colocated-network-lab"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count      = local.lab_count
  role       = aws_iam_role.lab_host[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "lab_host" {
  count = local.lab_count
  name  = "${var.project_tag}-colocated-network-lab"
  role  = aws_iam_role.lab_host[0].name
}
