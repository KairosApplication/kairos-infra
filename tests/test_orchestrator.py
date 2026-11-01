"""Exercise the orchestration gates without credentials, network calls or AWS resources."""
import json
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_deploy_setup import check
from deployment_summary import STAGES, report


class OrchestratorTests(unittest.TestCase):
    def environment(self):
        return {
            "AWS_ACCOUNT_ID": "123456789012", "AWS_REGION": "us-east-1",
            "TF_STATE_BUCKET": "kairos-state-test",
            "INFRA_CONFIG_JSON": json.dumps({"cluster_public_access_cidrs": ["203.0.113.10/32"]}),
            "DEPLOY_CONFIG_JSON": json.dumps({"mobile-api": {
                "api_host": "api.example.com",
                "certificate_arn": "arn:aws:acm:us-east-1:123456789012:certificate/test"}}),
            "RUNNER_APP_ID": "123", "RUNNER_APP_PRIVATE_KEY": "test-only-not-a-private-key",
            "GITHUB_REPOSITORY": "KairosApplication/kairos-infra", "GITHUB_REF": "refs/heads/main",
            "AWS_BOOTSTRAP_ROLE_ARN": "arn:aws:iam::123456789012:role/KairosBootstrap",
        }

    def test_oidc_and_direct_static_credentials_are_supported(self):
        check(self.environment())
        env = dict(self.environment(), AWS_BOOTSTRAP_ROLE_ARN="",
                   HAS_AWS_ACCESS_KEY_ID="true", HAS_AWS_SECRET_ACCESS_KEY="true")
        check(env)

    def test_aws_authentication_must_exist_and_key_pair_must_be_complete(self):
        for changes in (
            {"AWS_BOOTSTRAP_ROLE_ARN": ""},
            {"HAS_AWS_ACCESS_KEY_ID": "true"},
            {"HAS_AWS_SECRET_ACCESS_KEY": "true"},
            {"HAS_AWS_SESSION_TOKEN": "true"},
            {"AWS_BOOTSTRAP_ROLE_ARN": "arn:aws:iam::999999999999:role/OtherAccount"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                check(dict(self.environment(), **changes))

    def test_static_role_chain_requires_a_principal_in_the_same_account(self):
        env = dict(self.environment(), HAS_AWS_ACCESS_KEY_ID="true", HAS_AWS_SECRET_ACCESS_KEY="true")
        with self.assertRaises(ValueError):
            check(env)
        check(dict(env, AWS_STATIC_PRINCIPAL_ARN="arn:aws:iam::123456789012:user/KairosDeploy"))
        with self.assertRaises(ValueError):
            check(dict(env, AWS_STATIC_PRINCIPAL_ARN="arn:aws:iam::999999999999:user/OtherAccount"))

    def test_non_main_branch_is_rejected_before_aws_operations(self):
        with self.assertRaises(ValueError):
            check(dict(self.environment(), GITHUB_REF="refs/heads/feat/preview"))

    def test_success_requires_every_required_stage_and_never_reports_outputs(self):
        results = {key: {"result": "success", "outputs": {"secret": "never-display-this"}}
                   for key in STAGES}
        text, success = report(results)
        self.assertTrue(success)
        self.assertNotIn("never-display-this", text)
        self.assertIn("Fluxo concluido.", text)

    def test_skipped_failed_cancelled_or_missing_stages_cannot_report_success(self):
        for stage in STAGES:
            for result in ("failure", "skipped", "cancelled", "unexpected"):
                results = {key: {"result": "success"} for key in STAGES}
                results[stage]["result"] = result
                with self.subTest(stage=stage, result=result):
                    text, success = report(results)
                    self.assertFalse(success)
                    self.assertIn("Fluxo nao concluido", text)
        self.assertFalse(report({})[1])

    def test_deployment_cannot_bypass_any_validation_and_uses_local_workflows(self):
        workflow = yaml.load((ROOT / ".github/workflows/deploy-apis.yml").read_text(encoding="utf-8"),
                             Loader=yaml.BaseLoader)
        jobs = workflow["jobs"]
        gates = {"configuration", "repository-validation", "infrastructure-validation", "secret-scan"}
        self.assertEqual(set(jobs["deploy"]["needs"]), gates)
        self.assertNotIn("if", jobs["deploy"])
        self.assertNotIn("continue-on-error", jobs["deploy"])
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        for key in gates - {"configuration"}:
            job = jobs[key]
            target = ROOT / job["uses"].removeprefix("./")
            called = yaml.load(target.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
            self.assertIn("workflow_call", called["on"])
            self.assertNotIn("secrets", job)
            self.assertEqual(job["needs"], "configuration")
        full = yaml.load((ROOT / ".github/workflows/full-deploy.yml").read_text(encoding="utf-8"),
                         Loader=yaml.BaseLoader)
        self.assertTrue(set(jobs["deploy"]["secrets"]) <= set(full["on"]["workflow_call"]["secrets"]))
        self.assertNotEqual(workflow["concurrency"]["group"], full["concurrency"]["group"])
