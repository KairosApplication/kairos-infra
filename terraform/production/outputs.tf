output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "cluster_security_group_id" {
  value = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}

output "deployment_runner_security_group_id" {
  value = aws_security_group.deployment_runner.id
}

output "services" {
  value = {
    for name, service in var.services : name => {
      namespace          = service.namespace
      github_repository  = service.github_repository
      ecr_repository     = aws_ecr_repository.api[name].name
      image_repository   = aws_ecr_repository.api[name].repository_url
      secret_name        = aws_secretsmanager_secret.api[name].name
      runtime_role_arn   = aws_iam_role.runtime[name].arn
      publisher_role_arn = try(aws_iam_role.publisher[name].arn, null)
      deployer_role_arn  = try(aws_iam_role.deployer[name].arn, null)
    }
  }
}
