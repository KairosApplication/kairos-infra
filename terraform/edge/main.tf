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
    tags = { Project = "Kairos", Environment = "production", ManagedBy = "Terraform" }
  }
}
variable "aws_region" { type = string }
variable "aws_account_id" { type = string }
variable "cluster_name" { type = string }
variable "origins" { type = map(object({ arn = string, dns = string })) }

data "aws_cloudfront_cache_policy" "disabled" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_origin_request_policy" "api" { name = "Managed-AllViewerAndCloudFrontHeaders-2022-06" }

resource "aws_cloudfront_vpc_origin" "api" {
  for_each = var.origins
  vpc_origin_endpoint_config {
    name                   = "${var.cluster_name}-${each.key}"
    arn                    = each.value.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"
    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
  lifecycle { prevent_destroy = true }
}
resource "aws_cloudfront_distribution" "api" {
  for_each            = var.origins
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.cluster_name} ${each.key}"
  wait_for_deployment = true
  origin {
    origin_id   = each.key
    domain_name = each.value.dns
    vpc_origin_config { vpc_origin_id = aws_cloudfront_vpc_origin.api[each.key].id }
  }
  default_cache_behavior {
    target_origin_id         = each.key
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.api.id
    compress                 = true
  }
  dynamic "custom_error_response" {
    for_each = toset([400, 403, 404, 405, 414, 416, 500, 501, 502, 503, 504])
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
  lifecycle { prevent_destroy = true }
}
output "api_urls" { value = { for name, distribution in aws_cloudfront_distribution.api : name => "https://${distribution.domain_name}" } }
