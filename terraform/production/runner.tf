resource "aws_iam_role" "runner" {
  count = var.provision_deployment_runner ? 1 : 0
  name  = "${local.name}-runner-ssm"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "runner_ssm" {
  count      = var.provision_deployment_runner ? 1 : 0
  role       = aws_iam_role.runner[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "runner" {
  count = var.provision_deployment_runner ? 1 : 0
  name  = "${local.name}-runner"
  role  = aws_iam_role.runner[0].name
}

resource "aws_instance" "runner" {
  count                       = var.provision_deployment_runner ? 1 : 0
  ami                         = var.deployment_runner_ami_id
  instance_type               = "t3.small"
  subnet_id                   = aws_subnet.private[0].id
  vpc_security_group_ids      = [aws_security_group.deployment_runner.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.runner[0].name
  metadata_options {
    http_tokens = "required"
  }
  root_block_device {
    encrypted   = true
    volume_size = 30
  }
  # Register the runner through SSM after creation. Never put registration
  # tokens or GitHub App private keys in user_data or the Terraform state.
  user_data  = <<-SCRIPT
    #!/bin/bash
    set -euo pipefail
    dnf install -y git python3 tar gzip libicu
    useradd --create-home --shell /bin/bash kairos-runner
  SCRIPT
  tags       = { Name = "${local.name}-deploy-runner" }
  depends_on = [aws_iam_role_policy_attachment.runner_ssm, aws_route.nat]
}

output "deployment_runner_instance_id" {
  value = try(aws_instance.runner[0].id, null)
}
