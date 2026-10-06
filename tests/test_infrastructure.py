"""Semantic checks of the actual Helm output; no cluster or AWS access."""
import importlib.util
import json
import os
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get("HELM_BINARY", "helm")
DIGEST = "sha256:" + "a" * 64
SHA = "b" * 40


def render(service="mobile-api", extra=(), check=True):
    namespace = "kairos-mobile-api" if service == "mobile-api" else "kairos-agent-api"
    args = [
        HELM, "template", service, str(ROOT / "charts/kairos-api"),
        "--namespace", namespace,
        "-f", str(ROOT / f"environments/production/{service}.yaml"),
        "--set-string", "image.repository=123456789012.dkr.ecr.us-east-1.amazonaws.com/kairos/" + service,
        "--set-string", "image.digest=" + DIGEST,
        "--set-string", "aws.region=us-east-1",
        "--set-string", "sourceRevision=" + SHA,
    ]
    if service == "mobile-api":
        args += [
            "--set-string", "ingress.host=api.kairos.example",
            "--set-string", "ingress.certificateArn=arn:aws:acm:us-east-1:123456789012:certificate/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]
    result = subprocess.run(args + list(extra), text=True, capture_output=True, check=check)
    if check:
        return {doc["kind"]: doc for doc in yaml.safe_load_all(result.stdout) if doc}
    return result


class ManifestTests(unittest.TestCase):
    def test_mobile_public_entry_uses_https_and_digest(self):
        docs = render()
        annotations = docs["Ingress"]["metadata"]["annotations"]
        self.assertEqual(annotations["alb.ingress.kubernetes.io/ssl-redirect"], "443")
        self.assertEqual(json.loads(annotations["alb.ingress.kubernetes.io/listen-ports"]),
                         [{"HTTP": 80}, {"HTTPS": 443}])
        self.assertEqual(docs["Ingress"]["spec"]["ingressClassName"], "kairos-public")
        container = docs["Deployment"]["spec"]["template"]["spec"]["containers"][0]
        self.assertTrue(container["image"].endswith("@" + DIGEST))
        self.assertEqual(docs["Service"]["spec"]["type"], "ClusterIP")

    def test_agent_has_no_external_entry_and_restricts_consumers(self):
        docs = render("agent-api")
        self.assertNotIn("Ingress", docs)
        self.assertEqual(docs["Service"]["spec"]["type"], "ClusterIP")
        source = docs["NetworkPolicy"]["spec"]["ingress"][0]["from"][0]
        self.assertEqual(source["namespaceSelector"]["matchLabels"],
                         {"kubernetes.io/metadata.name": "kairos-agent-client"})
        self.assertEqual(source["podSelector"]["matchLabels"],
                         {"app.kubernetes.io/name": "kairos-agent"})
        self.assertEqual(docs["Deployment"]["metadata"]["namespace"], "kairos-agent-api")

    def test_service_selector_matches_pods(self):
        docs = render()
        self.assertEqual(docs["Service"]["spec"]["selector"],
                         docs["Deployment"]["spec"]["template"]["metadata"]["labels"])

    def test_health_and_shutdown_do_not_restart_on_database_failure(self):
        docs = render()
        deployment = docs["Deployment"]["spec"]
        pod = deployment["template"]["spec"]
        container = pod["containers"][0]
        self.assertEqual(container["readinessProbe"]["httpGet"]["path"], "/health")
        self.assertIn("tcpSocket", container["livenessProbe"])
        self.assertEqual(deployment["strategy"]["rollingUpdate"]["maxUnavailable"], 0)
        self.assertGreaterEqual(pod["terminationGracePeriodSeconds"], 30)

    def test_credentials_are_scoped_and_not_in_configmap(self):
        docs = render()
        provider = docs["SecretProviderClass"]["spec"]
        self.assertEqual(provider["parameters"]["usePodIdentity"], "true")
        objects = yaml.safe_load(provider["parameters"]["objects"])
        self.assertEqual(objects[0]["objectName"], "kairos/production/mobile-api")
        keys = {item["key"] for item in provider["secretObjects"][0]["data"]}
        self.assertEqual(keys, {"DB_URL", "DB_USERNAME", "DB_PASSWORD", "REDIS_URL"})
        self.assertFalse(keys.intersection(docs["ConfigMap"]["data"]))
        pod = docs["Deployment"]["spec"]["template"]["spec"]
        self.assertEqual(pod["serviceAccountName"], "kairos-runtime")
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertTrue(pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"])

    def test_autoscaling_and_budget_can_be_enabled(self):
        docs = render(extra=["--set", "autoscaling.enabled=true", "--set", "autoscaling.minReplicas=2"])
        self.assertNotIn("replicas", docs["Deployment"]["spec"])
        self.assertEqual(docs["HorizontalPodAutoscaler"]["spec"]["minReplicas"], 2)
        self.assertIn("PodDisruptionBudget", docs)

    def test_public_entry_requires_a_certificate(self):
        result = render(extra=["--set-string", "ingress.certificateArn="], check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_image_digest_is_rejected(self):
        result = render(extra=["--set-string", "image.digest=latest"], check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_only_mobile_is_enabled(self):
        services = json.loads((ROOT / "services.json").read_text())
        self.assertEqual([name for name, data in services.items() if data["enabled"]], ["mobile-api"])
        spec = importlib.util.spec_from_file_location("select_service", ROOT / "scripts/select-service.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.select("mobile-api", "KairosApplication/kairos-springboot", SHA)["namespace"],
                         "kairos-mobile-api")
        with self.assertRaises(ValueError):
            module.select("agent-api", "KairosApplication/example", SHA)
        with self.assertRaises(ValueError):
            module.select("mobile-api", "KairosApplication/kairos-infra", SHA)
        with self.assertRaises(ValueError):
            module.select("mobile-api", "KairosApplication/kairos-springboot", "main")

    def test_custom_resource_permissions_stay_in_mobile_namespace(self):
        spec = importlib.util.spec_from_file_location("bootstrap_rbac", ROOT / "scripts/bootstrap-rbac.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        registry = json.loads((ROOT / "services.json").read_text())
        items = module.resources(registry)["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["metadata"]["namespace"] == "kairos-mobile-api" for item in items))
        role = next(item for item in items if item["kind"] == "Role")
        self.assertEqual(role["rules"][0]["resources"], ["secretproviderclasses"])
        binding = next(item for item in items if item["kind"] == "RoleBinding")
        self.assertEqual(binding["subjects"][0]["name"], "kairos:mobile-api:deploy")

    def test_yaml_and_workflow_deployment_contract(self):
        for path in [*ROOT.glob(".github/**/*.yml"), *ROOT.glob("platform/*.yaml"),
                     *ROOT.glob("examples/**/*.yml"), *ROOT.glob("environments/**/*.yaml")]:
            with self.subTest(path=path):
                list(yaml.load_all(path.read_text(), Loader=yaml.BaseLoader))
        workflow = yaml.load((ROOT / ".github/workflows/reusable-release.yml").read_text(),
                             Loader=yaml.BaseLoader)
        deploy = workflow["jobs"]["deploy"]
        self.assertEqual(deploy["environment"], "production")
        self.assertEqual(deploy["runs-on"], ["self-hosted", "linux", "x64", "kairos-eks"])
        script = deploy["steps"][-1]["run"]
        self.assertIn("--atomic --wait", script)
        self.assertNotIn("--create-namespace", script)
        self.assertEqual(workflow["jobs"]["publish"]["permissions"]["id-token"], "write")


if __name__ == "__main__":
    unittest.main()
