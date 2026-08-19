resource "aws_iam_role" "traffic" {
  count = local.lab_count
  name  = "${var.project_tag}-dashboard-lab-traffic"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "traffic" {
  count = local.lab_count
  name  = "${var.project_tag}-dashboard-lab-traffic"
  role  = aws_iam_role.traffic[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeTags",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.project_tag}-dash-lab-probe-*",
          "arn:aws:s3:::${var.project_tag}-dash-lab-probe-*/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count      = local.lab_count
  role       = aws_iam_role.traffic[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "traffic" {
  count = local.lab_count
  name  = "${var.project_tag}-dashboard-lab-traffic"
  role  = aws_iam_role.traffic[0].name
}
