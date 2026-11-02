"""Exercise failure recovery, database capacity and Secrets Manager version transitions."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sync_runtime import sync_value
import diagnostics
import preflight_database as database
import rollout
import smoke


class VersionStore:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def __init__(self):
        self.versions = {}
        self.current = None

    def get_secret_value(self, **args):
        if self.current is None:
            raise self.exceptions.ResourceNotFoundException()
        return {"VersionId": self.current, "SecretString": self.versions[self.current]}

    def put_secret_value(self, **args):
        # Documented AWS semantics: an existing id+value is a no-op, including stages.
        version = args.get("ClientRequestToken", str(len(self.versions) + 1))
        if version not in self.versions:
            self.versions[version] = args["SecretString"]
            self.current = version
        return {"VersionId": version}


class RecoveryTests(unittest.TestCase):
    def test_runtime_revert_makes_a_new_current_version_without_duplicate_noops(self):
        store = VersionStore()
        a, b = {"DB_PASSWORD": "fixture-A"}, {"DB_PASSWORD": "fixture-B"}
        first = sync_value(store, "fixture", a)
        self.assertEqual(sync_value(store, "fixture", a), first)
        second = sync_value(store, "fixture", b)
        third = sync_value(store, "fixture", a)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertEqual(json.loads(store.get_secret_value()["SecretString"]), a)
        self.assertEqual(len(store.versions), 3)

    def report(self, **overrides):
        return dict({"database": "kairosdb", "schema": "public", "tls": True,
                     "max": 20, "reserved": 3, "used": 10,
                     "role_limit": -1, "role_used": 10, "db_limit": -1, "db_used": 10,
                     "tables": sorted(database.TABLES | {"restocking_history_delivery", "restocking_history_bypass"}), "history_present": True,
                     "history": [{"version": "3", "success": True}]}, **overrides)

    def test_preflight_rejects_actual_reserved_role_and_database_limits(self):
        self.assertEqual(database.validate(self.report(), "kairosdb", 3), 8)
        for overrides in ({"used": 17}, {"role_limit": 12}, {"db_limit": 12}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(database.PreflightError, "Conexoes"):
                database.validate(self.report(**overrides), "kairosdb", 3)

    def test_preflight_rejects_wrong_database_partial_baseline_and_failed_history(self):
        for overrides in ({"database": "defaultdb"}, {"schema": "other"}, {"tls": False},
                          {"tables": ["users"]}, {"tables": sorted(database.TABLES)}, {"history_present": False},
                          {"history": [{"success": False}]}):
            with self.subTest(overrides=overrides), self.assertRaises(database.PreflightError):
                database.validate(self.report(**overrides), "kairosdb", 3)
        database.validate(self.report(tables=[], history_present=False, history=[]), "kairosdb", 3)

    def test_preflight_pod_keeps_credentials_outside_manifest_and_uses_read_only_sql(self):
        pod = database.pod_spec("kairos-mobile-api")
        container = pod["spec"]["containers"][0]
        self.assertFalse(pod["spec"]["automountServiceAccountToken"])
        self.assertNotIn("envFrom", container)
        self.assertNotIn("secretKeyRef", json.dumps(pod))
        self.assertIn("default_transaction_read_only=on", container["command"][2])
        self.assertIn("sslmode=require", container["command"][2])
        self.assertIn("PGCONNECT_TIMEOUT=10", container["command"][2])
        self.assertEqual(pod["spec"]["serviceAccountName"], "kairos-runtime")

    def test_probe_shell_accepts_tls_uri_and_rejects_insecure_or_embedded_credentials(self):
        shell = database.pod_spec("ns")["spec"]["containers"][0]["command"][2]
        prefix = '''cat() { case "$1" in */DB_URL) printf '%s' "$FIXTURE_URL";; *) printf '%s' fixture;; esac; }
psql() { printf '%s' PSQL_CALLED; }
'''
        for uri, expected in (("jdbc:postgresql://db/kairosdb?sslmode=require", 0),
                              ("jdbc:postgresql://db/kairosdb?sslmode=disable", 2),
                              ("jdbc:postgresql://db/kairosdb?sslmode=disable&sslmode=require", 2),
                              ("jdbc:postgresql://user:fixture@db/kairosdb?sslmode=require", 2)):
            with self.subTest(uri=uri):
                result = subprocess.run([os.environ.get("KAIROS_TEST_BASH", "bash"), "--noprofile", "--norc"],
                                        input=prefix+shell, text=True, capture_output=True,
                                        env=dict(os.environ, FIXTURE_URL=uri, PREFLIGHT_SQL="SELECT 1", HISTORY_SQL="SELECT 1"))
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual("PSQL_CALLED" in result.stdout, expected == 0)

    def test_cold_install_prepares_adoptable_account_and_isolated_provider(self):
        from test_infrastructure import render
        documents = render()
        account = documents["ServiceAccount"]
        provider = documents["SecretProviderClass"]
        calls = []
        with patch.object(database, "render_object", side_effect=[account, provider]), \
             patch.object(database, "kube", return_value=SimpleNamespace(stdout="")), \
             patch.object(database.subprocess, "run", side_effect=lambda *a, **kw: calls.append(json.loads(kw["input"]))):
            database.prepare_probe_resources("kairos-mobile-api", "values", "overrides")
        self.assertEqual(calls[0]["metadata"]["annotations"]["meta.helm.sh/release-name"], "mobile-api")
        self.assertEqual(calls[0]["metadata"]["labels"]["app.kubernetes.io/managed-by"], "Helm")
        self.assertNotIn("secretObjects", calls[1]["spec"])
        projections = json.loads(calls[1]["spec"]["parameters"]["objects"])[0]["jmesPath"]
        self.assertEqual({p["objectAlias"] for p in projections}, {"DB_URL", "DB_USERNAME", "DB_PASSWORD"})

    def test_error_signatures_do_not_echo_credentials_or_customer_data(self):
        raw = "Caused by: org.postgresql.util.PSQLException: fixture-secret customer-cpf\nFATAL: remaining connection slots are reserved fixture-secret"
        with patch.object(diagnostics, "kube", return_value=SimpleNamespace(stdout=raw)):
            result = "\n".join(diagnostics.error_lines("ns", "pod"))
        self.assertIn("org.postgresql.util.PSQLException", result)
        self.assertIn("remaining connection slots", result)
        self.assertNotIn("fixture-secret", result)
        self.assertNotIn("customer-cpf", result)

    def test_status_preserves_previous_oom_without_dumping_env_or_messages(self):
        pod = {"metadata": {"name": "probe"}, "spec": {"env": "fixture-secret"},
               "status": {"phase": "Running", "containerStatuses": [{"name": "api",
                    "state": {"waiting": {"reason": "CrashLoopBackOff", "message": "customer-cpf"}},
                    "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}}}]}}
        with patch.object(diagnostics, "kube", side_effect=[SimpleNamespace(stdout=json.dumps(pod)),
                           SimpleNamespace(stdout=json.dumps({"items": []}))]):
            result = "\n".join(diagnostics.summary("ns", pod_name="probe"))
        self.assertIn("OOMKilled", result)
        self.assertNotIn("fixture-secret", result)
        self.assertNotIn("customer-cpf", result)

    def test_collector_starts_before_atomic_helm_can_remove_the_failing_pod(self):
        started = threading.Event()
        def collect(namespace, release, stop, path):
            path.write_text("captured-before-rollback")
            started.set()
            stop.wait(2)
        def helm(*args, **kwargs):
            self.assertTrue(started.wait(2))
            self.assertIn("--atomic", args[0])
            return SimpleNamespace(returncode=1)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, RUNNER_TEMP=directory), \
             patch.object(rollout, "collect", side_effect=collect), contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit):
                rollout.run("mobile-api", "ns", "values", "overrides", command=helm)
            self.assertIn("captured-before-rollback", output.getvalue())

    def test_initial_transition_restores_original_count_when_preflight_fails(self):
        def kubectl(namespace, *args, **kwargs):
            if args[:2] == ("get", "deployment"):
                return SimpleNamespace(stdout=json.dumps({"spec": {"replicas": 1}}))
            return SimpleNamespace(stdout=json.dumps({"items": []}))
        with patch.object(rollout, "kube", side_effect=kubectl), patch.object(rollout, "assert_unlocked"), \
             patch.object(database, "run", side_effect=database.PreflightError("fixture failure")), \
             patch.object(rollout, "restore_replicas") as restore, patch.object(rollout, "run") as upgrade:
            with self.assertRaises(database.PreflightError):
                rollout.deploy("mobile-api", "ns", "values", "overrides", initial_pool_transition=True)
            restore.assert_called_once_with("ns", "mobile-api", 1)
            upgrade.assert_not_called()

    def test_pending_helm_release_is_rejected_before_any_downtime(self):
        with patch.object(rollout.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps({"info": {"status": "pending-upgrade"}}))), \
             patch.object(rollout, "kube") as kubectl:
            with self.assertRaisesRegex(ValueError, "pendente"):
                rollout.deploy("mobile-api", "ns", "values", "overrides", initial_pool_transition=True)
            kubectl.assert_not_called()

    def test_normal_deploy_never_scales_down_and_checks_database_before_helm(self):
        order = []
        with patch.object(rollout, "kube") as kubectl, patch.object(rollout, "assert_unlocked"), \
             patch.object(database, "run", side_effect=lambda *a: order.append("preflight")), \
             patch.object(rollout, "run", side_effect=lambda *a: order.append("helm")):
            rollout.deploy("mobile-api", "ns", "values", "overrides")
        self.assertEqual(order, ["preflight", "helm"])
        kubectl.assert_not_called()

    def test_restore_only_restarts_a_deployment_left_at_zero(self):
        for current, expected in ((0, True), (1, False), (2, False)):
            with self.subTest(current=current), patch.object(rollout, "kube",
                    return_value=SimpleNamespace(stdout=json.dumps({"spec": {"replicas": current}}))) as kube:
                rollout.restore_replicas("ns", "mobile-api", 1)
                self.assertEqual(kube.call_count, 2 if expected else 1)

    def test_smoke_collects_diagnostics_before_deleting_failed_probe(self):
        order = []
        def run(args, **kwargs):
            if "wait" in args:
                raise subprocess.CalledProcessError(1, args)
            if "delete" in args:
                order.append("delete")
            return SimpleNamespace(returncode=0)
        with patch.object(smoke.subprocess, "run", side_effect=run), \
             patch.object(smoke, "summary", side_effect=lambda *a, **kw: order.append("diagnostics") or []), \
             patch.object(smoke, "error_lines", return_value=[]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                smoke.main()
        self.assertEqual(order, ["delete", "diagnostics", "delete"])

    def test_workflow_budget_includes_rollback_preflight_and_diagnostics(self):
        workflow = yaml.load((ROOT / ".github/workflows/reusable-release.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertGreaterEqual(int(workflow["jobs"]["deploy"]["timeout-minutes"]), 15 + 15 + 8)
        step = next(s for s in workflow["jobs"]["deploy"]["steps"] if s.get("id") == "rollout")
        self.assertIn("scripts/rollout.py", step["run"])

    def test_initial_transition_is_opt_in_and_only_reaches_mobile_service(self):
        load = lambda name: yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)
        for name in ("deploy-apis.yml", "full-deploy.yml"):
            workflow = load(name)
            self.assertEqual(workflow["on"]["workflow_dispatch"]["inputs"]["initial-pool-transition"]["default"], "false")
        expr = load("reconcile.yml")["jobs"]["release"]["with"]["initial-pool-transition"]
        self.assertIn("matrix.service == 'mobile-api'", expr)
