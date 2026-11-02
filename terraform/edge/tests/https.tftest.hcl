mock_provider "aws" {}
variables {
  aws_region     = "us-east-2"
  aws_account_id = "123456789012"
  cluster_name   = "kairos-production"
  origins = { mobile-api = {
    arn = "arn:aws:elasticloadbalancing:us-east-2:123456789012:loadbalancer/app/api/id"
    dns = "internal-kairos-123.us-east-2.elb.amazonaws.com"
    }, agent-api = {
    arn = "arn:aws:elasticloadbalancing:us-east-2:123456789012:loadbalancer/app/agent/other"
    dns = "internal-kairos-agent-123.us-east-2.elb.amazonaws.com"
  } }

}
run "private_origin_https_api" {
  command = plan
  assert {
    condition     = length(aws_cloudfront_distribution.api) == 2 && aws_cloudfront_distribution.api["agent-api"].viewer_certificate[0].cloudfront_default_certificate
    error_message = "As duas APIs publicas precisam de distribuicoes HTTPS independentes."
  }
  assert {
    condition     = aws_cloudfront_distribution.api["mobile-api"].viewer_certificate[0].cloudfront_default_certificate
    error_message = "O dominio padrao deve usar o certificado AWS sem ACM proprio."
  }
  assert {
    condition     = aws_cloudfront_distribution.api["mobile-api"].default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    error_message = "Clientes devem usar HTTPS."
  }
  assert {
    condition     = length(aws_cloudfront_distribution.api["mobile-api"].default_cache_behavior[0].allowed_methods) == 7
    error_message = "A API precisa encaminhar POST, PUT, PATCH, DELETE e OPTIONS."
  }
  assert {
    condition     = alltrue([for response in aws_cloudfront_distribution.api["mobile-api"].custom_error_response : response.error_caching_min_ttl == 0])
    error_message = "Erros autenticados nao devem ficar em cache."
  }
}
