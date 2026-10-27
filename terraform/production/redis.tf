variable "provision_redis" {
  type    = bool
  default = false
}
variable "redis_auth_token" {
  type      = string
  sensitive = true
  ephemeral = true
  default   = null
  validation {
    condition     = !var.provision_redis || can(regex("^[A-Za-z0-9_-]{32,128}$", var.redis_auth_token))
    error_message = "Redis gerenciado exige token ephemeral com 32 a 128 caracteres alfanumericos, _ ou -."
  }
}
variable "redis_auth_version" {
  type    = number
  default = 1
}
resource "aws_elasticache_subnet_group" "redis" {
  count      = var.provision_redis ? 1 : 0
  name       = "${local.name}-redis"
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_security_group" "redis" {
  count       = var.provision_redis ? 1 : 0
  name        = "${local.name}-redis"
  description = "TLS Redis from EKS nodes only"
  vpc_id      = aws_vpc.main.id
}
resource "aws_vpc_security_group_ingress_rule" "redis_from_eks" {
  count                        = var.provision_redis ? 1 : 0
  security_group_id            = aws_security_group.redis[0].id
  referenced_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}
resource "aws_elasticache_replication_group" "redis" {
  count                      = var.provision_redis ? 1 : 0
  replication_group_id       = "${local.name}-redis"
  description                = "Kairos session and restocking cache"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token_wo              = var.redis_auth_token
  auth_token_wo_version      = var.redis_auth_version
  auth_token_update_strategy = "SET"
  subnet_group_name          = aws_elasticache_subnet_group.redis[0].name
  security_group_ids         = [aws_security_group.redis[0].id]
  snapshot_retention_limit   = 7
  auto_minor_version_upgrade = true
  apply_immediately          = false
  lifecycle {
    prevent_destroy = true
  }
}
output "redis_endpoint" {
  value = try(aws_elasticache_replication_group.redis[0].primary_endpoint_address, null)
}
