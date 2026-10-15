resource "aws_security_group" "deployment_runner" {
  name        = "${local.name}-deploy-runner"
  description = "Dedicated deployment runner; HTTPS egress, no inbound ports."
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.name}-deploy-runner" }
}

resource "aws_vpc_security_group_egress_rule" "runner_https" {
  security_group_id = aws_security_group.deployment_runner.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "cluster_from_runner" {
  security_group_id            = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_security_group.deployment_runner.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "Private Kubernetes API access for the deployment runner."
}
