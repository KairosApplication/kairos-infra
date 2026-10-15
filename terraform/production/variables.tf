variable "aws_region" {
  type        = string
  description = "Regiao AWS para todos os recursos."
}

variable "aws_account_id" {
  type        = string
  description = "ID da conta autorizada a receber os recursos."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Informe o ID AWS com 12 digitos."
  }
}

variable "cluster_name" {
  type    = string
  default = "kairos-production"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,39}$", var.cluster_name))
    error_message = "Use de 2 a 40 caracteres minusculos, numeros e hifens."
  }
}

variable "kubernetes_version" {
  type        = string
  default     = "1.35"
  description = "Versao EKS fixada, revisar antes do fim do suporte padrao."
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "single_nat_gateway" {
  type        = bool
  default     = true
  description = "Um NAT reduz custo, mas nao oferece resiliencia do NAT entre AZs."
}

variable "cluster_public_access_cidrs" {
  type        = list(string)
  description = "IPs CIDR dos operadores. O runner de deploy usa o endpoint privado."
  validation {
    condition = length(var.cluster_public_access_cidrs) > 0 && alltrue([
      for cidr in var.cluster_public_access_cidrs :
      can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"
    ])
    error_message = "Informe pelo menos um CIDR IPv4 restrito; 0.0.0.0/0 nao e permitido."
  }
}

variable "cluster_admin_principal_arns" {
  type        = set(string)
  description = "ARNs permanentes de roles/usuarios administradores, nunca ARN de sessao STS."
  validation {
    condition = length(var.cluster_admin_principal_arns) > 0 && alltrue([
      for arn in var.cluster_admin_principal_arns :
      can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/.+$", arn))
    ])
    error_message = "Informe pelo menos um ARN IAM de role ou usuario administrador."
  }
}

variable "github_oidc_provider_arn" {
  type        = string
  default     = null
  description = "Provider GitHub OIDC existente; null cria o provider na conta."
  nullable    = true
}

variable "github_static_principal_arns" {
  type        = map(string)
  default     = {}
  description = "Opcional: principal IAM por servico para assumir roles com chaves GitHub Secrets; OIDC permanece disponivel."
  validation {
    condition = alltrue([
      for service, arn in var.github_static_principal_arns :
      contains(keys(var.services), service) && can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/.+$", arn))
    ])
    error_message = "Use apenas servicos cadastrados e ARNs IAM permanentes."
  }
}

variable "provision_deployment_runner" {
  type        = bool
  default     = false
  description = "Cria maquina privada SSM; registro no GitHub e realizado separadamente."
}

variable "deployment_runner_ami_id" {
  type        = string
  default     = null
  description = "AMI Amazon Linux 2023 x86_64 na regiao, com SSM e AWS CLI v2."
  validation {
    condition     = !var.provision_deployment_runner || can(regex("^ami-[a-f0-9]{8,17}$", var.deployment_runner_ami_id))
    error_message = "Informe uma AMI Amazon Linux 2023 x86_64 quando provisionar o runner."
  }
}

variable "services" {
  type = map(object({
    namespace         = string
    github_repository = optional(string)
  }))
  default = {
    mobile-api = {
      namespace         = "kairos-mobile-api"
      github_repository = "KairosApplication/kairos-springboot"
    }
  }
  description = "Apenas servicos prontos. Adicionar agent-api quando a segunda API existir."
  validation {
    condition = length(var.services) > 0 && alltrue([
      for name, service in var.services :
      can(regex("^[a-z][a-z0-9-]{0,38}[a-z0-9]$", name)) &&
      can(regex("^[a-z][a-z0-9-]{0,61}[a-z0-9]$", service.namespace)) &&
      (service.github_repository == null ? true : can(regex("^KairosApplication/[A-Za-z0-9_.-]+$", service.github_repository)))
    ])
    error_message = "Use nome de servico e namespace validos e repositorio da KairosApplication."
  }
  validation {
    condition     = length(distinct([for service in var.services : service.namespace])) == length(var.services)
    error_message = "Cada API precisa de um namespace exclusivo."
  }
}
