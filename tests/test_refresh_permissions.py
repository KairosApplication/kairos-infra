"""Check refresh API contracts against generated IAM, including existing resources.

This checks the identity-policy allowlist only; it is not an AWS IAM simulator
and does not evaluate SCPs, permission boundaries, or live account state.
"""
import fnmatch
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pipeline_bootstrap import policies

# Explicit inventory, independent of the policy under test. New Terraform
# resource types must declare their refresh API contract here.
CONTRACTS = {}


def contract(kinds, resource, actions):
    for kind in kinds.split():
        CONTRACTS[kind] = (resource, actions.split())


contract("aws_vpc aws_internet_gateway aws_subnet aws_route_table aws_route aws_route_table_association aws_eip aws_nat_gateway aws_vpc_endpoint aws_security_group aws_vpc_security_group_ingress_rule aws_vpc_security_group_egress_rule",
         "*", "ec2:DescribeVpcs ec2:DescribeInternetGateways ec2:DescribeSubnets ec2:DescribeRouteTables ec2:DescribeAddresses ec2:DescribeNatGateways ec2:DescribeVpcEndpoints ec2:DescribeSecurityGroups ec2:DescribeSecurityGroupRules")
contract("aws_instance", "*", "ec2:DescribeInstances ec2:DescribeInstanceAttribute ec2:DescribeInstanceTypes ec2:DescribeVolumes ec2:DescribeTags")
contract("aws_iam_role aws_iam_role_policy aws_iam_role_policy_attachment",
         "arn:aws:iam::123456789012:role/kairos-production-mobile-api-runtime",
         "iam:GetRole iam:GetRolePolicy iam:ListAttachedRolePolicies iam:ListRolePolicies")
contract("aws_iam_instance_profile", "arn:aws:iam::123456789012:instance-profile/kairos-production-runner", "iam:GetInstanceProfile")
contract("aws_iam_openid_connect_provider", "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com", "iam:GetOpenIDConnectProvider")
contract("aws_cloudwatch_log_group", "arn:aws:logs:us-east-1:123456789012:log-group:/aws/eks/kairos-production/cluster", "logs:DescribeLogGroups logs:ListTagsForResource logs:ListTagsLogGroup")
contract("aws_eks_cluster aws_eks_access_entry aws_eks_access_policy_association aws_eks_pod_identity_association",
         "*", "eks:DescribeCluster eks:DescribeAccessEntry eks:ListAssociatedAccessPolicies eks:DescribePodIdentityAssociation eks:ListTagsForResource")
contract("aws_ecr_repository", "arn:aws:ecr:us-east-1:123456789012:repository/kairos/mobile-api", "ecr:DescribeRepositories ecr:ListTagsForResource")
contract("aws_ecr_lifecycle_policy", "arn:aws:ecr:us-east-1:123456789012:repository/kairos/mobile-api", "ecr:GetLifecyclePolicy")
contract("aws_elasticache_subnet_group aws_elasticache_replication_group", "*", "elasticache:DescribeCacheSubnetGroups elasticache:DescribeReplicationGroups elasticache:DescribeCacheClusters elasticache:ListTagsForResource")
contract("aws_secretsmanager_secret", "arn:aws:secretsmanager:us-east-1:123456789012:secret:kairos/production/mobile-api-example", "secretsmanager:DescribeSecret secretsmanager:GetResourcePolicy")
contract("aws_cloudfront_vpc_origin", "arn:aws:cloudfront::123456789012:vpcorigin/vo-example", "cloudfront:GetVpcOrigin cloudfront:ListTagsForResource")
contract("aws_cloudfront_distribution", "arn:aws:cloudfront::123456789012:distribution/EXAMPLE", "cloudfront:GetDistribution cloudfront:GetDistributionConfig cloudfront:ListTagsForResource")


def allows(policy, action, resource):
    for statement in policy["Statement"]:
        actions, resources = statement["Action"], statement["Resource"]
        actions = [actions] if isinstance(actions, str) else actions
        resources = [resources] if isinstance(resources, str) else resources
        if statement["Effect"] == "Allow" and not statement.get("Condition") and any(
                fnmatch.fnmatchcase(action, pattern) for pattern in actions) and any(
                fnmatch.fnmatchcase(resource, pattern) for pattern in resources):
            return True
    return False


class RefreshPermissionsTests(unittest.TestCase):
    def test_inventory_covers_every_managed_resource_type(self):
        kinds = {kind for directory in ("production", "edge")
                 for path in (ROOT / "terraform" / directory).glob("*.tf")
                 for kind in re.findall(r'^resource\s+"([^"]+)"', path.read_text(encoding="utf-8"), re.M)}
        self.assertEqual(kinds, set(CONTRACTS))

    def test_plan_and_apply_can_refresh_existing_resources(self):
        generated = policies("123456789012", "us-east-1", "kairos-state-test", "kairos-production")
        for role in ("plan", "apply"):
            for kind, (resource, actions) in CONTRACTS.items():
                for action in actions:
                    with self.subTest(role=role, resource=kind, action=action):
                        self.assertTrue(allows(generated[role], action, resource))

    def test_plan_can_resolve_edge_policies_and_remote_state(self):
        plan = policies("123456789012", "us-east-1", "kairos-state-test", "kairos-production")["plan"]
        for action in ("cloudfront:ListCachePolicies", "cloudfront:GetCachePolicy",
                       "cloudfront:ListOriginRequestPolicies", "cloudfront:GetOriginRequestPolicy",
                       "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTags"):
            self.assertTrue(allows(plan, action, "*"), action)
        for key in ("terraform", "cloudfront"):
            state = "arn:aws:s3:::kairos-state-test/production/" + key + ".tfstate"
            self.assertTrue(allows(plan, "s3:GetObject", state))
            self.assertTrue(allows(plan, "s3:PutObject", state + ".tflock"))
            self.assertTrue(allows(plan, "s3:DeleteObject", state + ".tflock"))
            self.assertFalse(allows(plan, "s3:DeleteObject", state))
