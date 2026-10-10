resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_oidc_provider_arn == null ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  github_oidc_arn = var.github_oidc_provider_arn != null ? var.github_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn
}

resource "aws_iam_role" "publisher" {
  for_each = local.source_services
  name     = "${local.name}-${each.key}-publish"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:KairosApplication/kairos-infra:ref:refs/heads/main"
        }
      }
      }], contains(keys(var.github_static_principal_arns), each.key) ? [{
      Effect    = "Allow"
      Principal = { AWS = var.github_static_principal_arns[each.key] }
      Action    = "sts:AssumeRole"
    }] : [])
  })
}

resource "aws_iam_role_policy" "publisher" {
  for_each = local.source_services
  role     = aws_iam_role.publisher[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage"
        ]
        Resource = aws_ecr_repository.api[each.key].arn
      }
    ]
  })
}

resource "aws_iam_role" "deployer" {
  for_each = local.source_services
  name     = "${local.name}-${each.key}-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:KairosApplication/kairos-infra:environment:production"
        }
      }
      }], contains(keys(var.github_static_principal_arns), each.key) ? [{
      Effect    = "Allow"
      Principal = { AWS = var.github_static_principal_arns[each.key] }
      Action    = "sts:AssumeRole"
    }] : [])
  })
}

resource "aws_iam_role_policy" "deployer" {
  for_each = local.source_services
  role     = aws_iam_role.deployer[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["eks:DescribeCluster"]
      Resource = aws_eks_cluster.main.arn
      }, {
      Effect   = "Allow"
      Action   = ["secretsmanager:DescribeSecret"]
      Resource = aws_secretsmanager_secret.api[each.key].arn
    }]
  })
}

resource "aws_eks_access_entry" "deployer" {
  for_each          = local.source_services
  cluster_name      = aws_eks_cluster.main.name
  principal_arn     = aws_iam_role.deployer[each.key].arn
  kubernetes_groups = ["kairos:${each.key}:deploy"]
  type              = "STANDARD"
}

resource "aws_eks_access_policy_association" "deployer" {
  for_each      = local.source_services
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_eks_access_entry.deployer[each.key].principal_arn
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
  access_scope {
    type       = "namespace"
    namespaces = [each.value.namespace]
  }
}
