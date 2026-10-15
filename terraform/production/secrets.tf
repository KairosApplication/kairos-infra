resource "aws_secretsmanager_secret" "api" {
  for_each                = var.services
  name                    = "kairos/production/${each.key}"
  description             = "Environment credentials for ${each.key}; values are configured outside Terraform."
  recovery_window_in_days = 30
}

resource "aws_iam_role" "runtime" {
  for_each = var.services
  name     = "${local.name}-${each.key}-runtime"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = {
        StringEquals = {
          "aws:RequestTag/kubernetes-namespace"       = each.value.namespace
          "aws:RequestTag/kubernetes-service-account" = "kairos-runtime"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "runtime" {
  for_each = var.services
  role     = aws_iam_role.runtime[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = aws_secretsmanager_secret.api[each.key].arn
    }]
  })
}

resource "aws_eks_pod_identity_association" "runtime" {
  for_each        = var.services
  cluster_name    = aws_eks_cluster.main.name
  namespace       = each.value.namespace
  service_account = "kairos-runtime"
  role_arn        = aws_iam_role.runtime[each.key].arn
}
