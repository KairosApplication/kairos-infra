"""Reject unsafe origin adoption and incomplete CloudFront configuration."""
import importlib.util
import tempfile
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_edge import select_origin
import test_full_pipeline
import pipeline_bootstrap

class CloudFrontTests(unittest.TestCase):
    def test_no_custom_domain_or_acm_is_required(self):
        env=test_full_pipeline.FullPipelineTests().environment()
        env["DEPLOY_CONFIG_JSON"]=json.dumps({"mobile-api":{"entrypoint":"cloudfront"}})
        _, deploy=pipeline_bootstrap.validate(env)
        self.assertEqual(deploy["mobile-api"]["entrypoint"],"cloudfront")
        for values in ({"entrypoint":"http"}, {"entrypoint":"cloudfront","api_host":"api.example.com"}):
            env["DEPLOY_CONFIG_JSON"]=json.dumps({"mobile-api":values})
            with self.assertRaises(ValueError):
                pipeline_bootstrap.validate(env)

    def test_only_cluster_owned_active_private_alb_is_adopted(self):
        host="internal-kairos-123.us-east-2.elb.amazonaws.com"
        lb={"DNSName":host, "Scheme":"internal", "Type":"application", "State":{"Code":"active"},
            "LoadBalancerArn":"arn:aws:elasticloadbalancing:us-east-2:123456789012:loadbalancer/app/api/id"}
        tags={"eks:eks-cluster-name":"kairos-production"}
        self.assertEqual(select_origin([lb],host,"kairos-production","123456789012",tags),lb)
        for changed in (dict(lb,Scheme="internet-facing"),dict(lb,State={"Code":"provisioning"}),
                        dict(lb,LoadBalancerArn=lb["LoadBalancerArn"].replace("123456789012","999999999999"))):
            with self.assertRaises(ValueError):
                select_origin([changed],host,"kairos-production","123456789012",tags)
        with self.assertRaises(ValueError):
            select_origin([lb],host,"kairos-production","123456789012",{})
        with self.assertRaises(ValueError):
            select_origin([lb,lb],host,"kairos-production","123456789012",tags)

    def test_cloudfront_overrides_preserve_https_without_trusting_client_host_port(self):
        spec=importlib.util.spec_from_file_location("release_values",ROOT/"scripts/release-values.py")
        release=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"release.json"
            args=["release-values", "--image-repository",
                  "123456789012.dkr.ecr.us-east-2.amazonaws.com/kairos/mobile-api",
                  "--digest", "sha256:"+"a"*64, "--source-sha", "b"*40,
                  "--region", "us-east-2", "--entrypoint", "cloudfront",
                  "--cloudfront-prefix-list-id", "pl-0123456789abcdef0", "--output", str(output)]
            with patch.object(sys,"argv",args):
                release.main()
            values=json.loads(output.read_text())
            self.assertEqual(values["env"]["SERVER_TOMCAT_REMOTEIP_PROTOCOL_HEADER"],"CloudFront-Forwarded-Proto")
            self.assertEqual(values["env"]["SERVER_FORWARD_HEADERS_STRATEGY"],"native")
            self.assertEqual(values["env"]["SERVER_TOMCAT_REMOTEIP_HOST_HEADER"],"")
            self.assertEqual(values["env"]["SERVER_TOMCAT_REMOTEIP_PORT_HEADER"],"")
