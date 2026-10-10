terraform {
  required_version = ">= 1.10, < 2.0"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]
  default_tags {
    tags = {
      Project     = "Kairos"
      Environment = "production"
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_partition" "current" {}

locals {
  name = var.cluster_name
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
  source_services = {
    for name, service in var.services : name => service
    if service.github_repository != null
  }
}
