"""Boundaries of first-run bootstrap, secret handling and private service access."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline_bootstrap as bootstrap
import register_runner
from sync_runtime import merge_runtime


class FullPipelineTests(unittest.TestCase):
    def environment(self):
        return {"AWS_ACCOUNT_ID": "123456789012", "AWS_REGION": "us-east-1",
                "TF_STATE_BUCKET": "kairos-state-test", "INFRA_CONFIG_JSON": json.dumps({
                    "cluster_public_access_cidrs": ["203.0.113.10/32"]}),
                "DEPLOY_CONFIG_JSON": json.dumps({"mobile-api": {
                    "api_host": "api.example.com",
                    "certificate_arn": "arn:aws:acm:us-east-1:123456789012:certificate/test"}}),
                "RUNNER_APP_ID": "123", "RUNNER_APP_PRIVATE_KEY": "test-only-not-a-key",
                "GITHUB_REPOSITORY": "KairosApplication/kairos-infra", "GITHUB_REF": "refs/heads/main"}

    def test_first_run_requires_configuration_and_main(self):
        env = self.environment()
        config, _ = bootstrap.validate(env)
        self.assertTrue(config["provision_redis"])
        self.assertTrue(config["provision_deployment_runner"])
        for key in ("AWS_ACCOUNT_ID", "DEPLOY_CONFIG_JSON", "RUNNER_APP_PRIVATE_KEY"):
            broken = dict(env)
            broken.pop(key)
            with self.assertRaises(ValueError):
                bootstrap.validate(broken)
        with self.assertRaises(ValueError):
            bootstrap.validate(dict(env, GITHUB_REF="refs/heads/feature"))

    def test_role_trust_has_exact_repository_and_environment(self):
        trust = bootstrap.trust("arn:provider", "environment:infrastructure-production")
        self.assertEqual(trust["Statement"][0]["Condition"]["StringEquals"][
            "token.actions.githubusercontent.com:sub"],
            "repo:KairosApplication/kairos-infra:environment:infrastructure-production")
        self.assertNotIn("Principal", trust)

    def test_plan_cannot_read_runtime_credentials(self):
        policy = bootstrap.policies("123456789012", "us-east-1", "kairos-state-test", "kairos-production")
        reads = [s for s in policy["plan"]["Statement"] if "secretsmanager:GetSecretValue" in s["Action"]]
        self.assertEqual(len(reads), 1)
        self.assertIn("/redis-auth-", reads[0]["Resource"])
        self.assertNotIn("production/mobile-api", reads[0]["Resource"])
        deletes = [s for s in policy["plan"]["Statement"] if "s3:DeleteObject" in s["Action"]]
        self.assertTrue(all(s["Resource"].endswith(".tflock") for s in deletes))

    def test_runtime_preserves_database_and_adds_only_internal_credentials(self):
        existing = {"DB_URL": "jdbc:postgresql://db/kairos", "DB_USERNAME": "app",
                    "DB_PASSWORD": "test-only", "AUTH_SIGNING_KEY": "existing"}
        value = merge_runtime(existing, {}, "rediss://test-only@cache/0", "internal-test")
        self.assertEqual(value["DB_PASSWORD"], existing["DB_PASSWORD"])
        self.assertEqual(value["AUTH_SIGNING_KEY"], "existing")
        self.assertEqual(value["KAIROS_INTERNAL_API_KEY"], "internal-test")
        with self.assertRaises(ValueError):
            merge_runtime({}, {}, "rediss://cache/0", "internal-test")

    def test_runner_command_contains_parameter_reference_not_secret(self):
        script = register_runner.remote_script(
            "https://github.com/actions/runner/releases/download/v1/runner.tar.gz",
            "a" * 64, "/kairos/runner/i-123/registration", "us-east-1", "kairos-i-123")
        self.assertIn("--with-decryption", script)
        self.assertIn("sha256sum --check", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", script)
        with self.assertRaises(ValueError):
            register_runner.remote_script("https://untrusted.example/file", "a"*64, "/parameter", "us-east-1", "name")

    def test_full_workflow_orders_dependencies_and_does_not_dispatch_remotely(self):
        doc = yaml.load((ROOT / ".github/workflows/full-deploy.yml").read_text(), Loader=yaml.BaseLoader)
        jobs = doc["jobs"]
        self.assertEqual(jobs["infrastructure"]["needs"], "bootstrap")
        self.assertIn("infrastructure", jobs["runner"]["needs"])
        self.assertIn("runner", jobs["platform"]["needs"])
        self.assertIn("platform", jobs["applications"]["needs"])
        self.assertIn("applications", jobs["verify"]["needs"])
        self.assertIn("verify", jobs["summary"]["needs"])
        self.assertNotIn("workflow_run", doc["on"])
