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
    condition     = jsondecode(aws_iam_role.deployer["mobile-api"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:KairosApplication/kairos-infra:environment:production"
    error_message = "Deploy deve aceitar somente o ambiente production do infra."
  }
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
    condition     = jsondecode(aws_iam_role.publisher["mobile-api"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:KairosApplication/kairos-infra:ref:refs/heads/main"
    error_message = "Publicacao ECR deve aceitar somente main do repositorio de infra."
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

run "new_service_and_optional_static_credentials" {
  command = apply
  variables {
    services = {
      catalog-api = {
        namespace         = "kairos-catalog-api"
        github_repository = "KairosApplication/catalog-api"
      }
    }
    github_static_principal_arns = {
      catalog-api = "arn:aws:iam::123456789012:user/CatalogPublisher"
    }
    provision_deployment_runner = true
    deployment_runner_ami_id    = "ami-0123456789abcdef0"
  }
  assert {
    condition     = length(aws_ecr_repository.api) == 1 && contains(keys(aws_ecr_repository.api), "catalog-api")
    error_message = "Novos servicos cadastrados devem criar recursos sem alterar uma lista fixa."
  }
  assert {
    condition     = jsondecode(aws_iam_role.deployer["catalog-api"].assume_role_policy).Statement[1].Principal.AWS == "arn:aws:iam::123456789012:user/CatalogPublisher"
    error_message = "Chaves devem assumir somente roles explicitamente confiaveis."
  }
  assert {
    condition     = !aws_instance.runner[0].associate_public_ip_address && aws_instance.runner[0].metadata_options[0].http_tokens == "required"
    error_message = "Runner deve ser privado e exigir IMDSv2."
  }
}
