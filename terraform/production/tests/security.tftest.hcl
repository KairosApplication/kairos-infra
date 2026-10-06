mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1a", "us-east-1b"] }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock-role" }
  }
  mock_resource "aws_eks_cluster" {
    defaults = { arn = "arn:aws:eks:us-east-1:123456789012:cluster/mock" }
  }
  mock_resource "aws_ecr_repository" {
    defaults = { arn = "arn:aws:ecr:us-east-1:123456789012:repository/mock" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-123456" }
  }
}

variables {
  aws_region                   = "us-east-1"
  aws_account_id               = "123456789012"
  cluster_public_access_cidrs  = ["203.0.113.10/32"]
  cluster_admin_principal_arns = ["arn:aws:iam::123456789012:role/TestAdmin"]
}

run "mobile_only" {
  # Apply is simulated by mock_provider: no AWS calls or live resources.
  command = apply
  assert {
    condition     = length(aws_ecr_repository.api) == 1 && contains(keys(aws_ecr_repository.api), "mobile-api")
    error_message = "A API do agente nao pode criar recursos enquanto estiver desabilitada."
  }
  assert {
    condition     = aws_ecr_repository.api["mobile-api"].image_tag_mutability == "IMMUTABLE"
    error_message = "As imagens de release precisam ter tags imutaveis."
  }
  assert {
    condition     = aws_eks_access_policy_association.deployer["mobile-api"].access_scope[0].type == "namespace" && aws_eks_access_policy_association.deployer["mobile-api"].access_scope[0].namespaces == toset(["kairos-mobile-api"])
    error_message = "O deploy da API deve ficar limitado ao seu namespace."
  }
  assert {
    condition     = aws_eks_access_entry.deployer["mobile-api"].kubernetes_groups == toset(["kairos:mobile-api:deploy"])
    error_message = "O grupo RBAC do driver de segredos deve corresponder a API."
  }
  assert {
    condition     = aws_eks_cluster.main.deletion_protection && !aws_eks_cluster.main.access_config[0].bootstrap_cluster_creator_admin_permissions
    error_message = "O cluster deve ter protecao contra exclusao e acesso administrativo explicito."
  }
  assert {
    condition     = length(aws_nat_gateway.main) == 1 && length(aws_subnet.private) == 2
    error_message = "A topologia inicial deve usar duas AZs e um NAT."
  }
  assert {
    condition     = jsondecode(aws_iam_role.publisher["mobile-api"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:KairosApplication/kairos-springboot:ref:refs/heads/main"
    error_message = "Publicacao ECR deve aceitar somente main da API principal."
  }
}

run "reject_world_access" {
  command = plan
  variables {
    cluster_public_access_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.cluster_public_access_cidrs]
}

run "second_api_is_isolated" {
  command = apply
  variables {
    services = {
      mobile-api = {
        namespace         = "kairos-mobile-api"
        github_repository = "KairosApplication/kairos-springboot"
      }
      agent-api = {
        namespace         = "kairos-agent-api"
        github_repository = "KairosApplication/example-agent-api"
      }
    }
    single_nat_gateway = false
  }
  assert {
    condition     = length(aws_ecr_repository.api) == 2 && length(aws_nat_gateway.main) == 2
    error_message = "A segunda API e o NAT por AZ precisam ser configuraveis."
  }
  assert {
    condition     = aws_eks_access_policy_association.deployer["agent-api"].access_scope[0].namespaces == toset(["kairos-agent-api"])
    error_message = "A segunda API nao pode editar o namespace da API mobile."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.runtime["agent-api"].policy).Statement[0].Resource == aws_secretsmanager_secret.api["agent-api"].arn
    error_message = "A API do agente so pode ler seu proprio segredo."
  }
}
