"""Deployment allowlist, destructive-plan guard, and release state boundaries."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from registry import load_registry, terraform_services


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class AutomationTests(unittest.TestCase):
    def test_generated_terraform_includes_only_enabled_services(self):
        services = terraform_services(load_registry())
        self.assertEqual(set(services), {'mobile-api'})
        self.assertEqual(services['mobile-api']['github_repository'], 'KairosApplication/kairos-springboot')

    def test_registry_rejects_duplicate_namespace_and_external_repository(self):
        registry = load_registry()
        registry['new-api'] = dict(registry['mobile-api'], source_repository='KairosApplication/new-api',
                                   ecr_repository='kairos/new-api')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'services.json'
            path.write_text(json.dumps(registry), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_registry(path)
            registry['new-api']['namespace'] = 'kairos-new-api'
            registry['new-api']['source_repository'] = 'OtherOrganization/new-api'
            path.write_text(json.dumps(registry), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_registry(path)

    def test_new_service_does_not_require_changing_python_allowlist(self):
        registry = load_registry()
        registry['new-api'] = dict(registry['mobile-api'], namespace='kairos-new-api',
                                  source_repository='KairosApplication/new-api', ecr_repository='kairos/new-api')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'services.json'
            path.write_text(json.dumps(registry), encoding='utf-8')
            self.assertIn('new-api', terraform_services(load_registry(path)))

    def test_config_cannot_override_service_allowlist(self):
        prepare = module('prepare-infra')
        config = {'cluster_admin_principal_arns': ['arn:aws:iam::123456789012:role/Admin'],
                  'cluster_public_access_cidrs': ['203.0.113.10/32']}
        result = prepare.configuration(config, load_registry(), '123456789012', 'us-east-1', 'kairos-state-test')
        self.assertEqual(set(result['services']), {'mobile-api'})
        with self.assertRaises(ValueError):
            prepare.configuration(dict(config, services={}), load_registry(), '123456789012', 'us-east-1', 'kairos-state-test')

    def test_plan_rejects_delete_and_replacement(self):
        guard = module('check-plan')
        for actions in (['delete'], ['delete', 'create'], ['create', 'delete']):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                guard.inspect({'resource_changes': [{'address': 'aws_eks_cluster.main',
                                                      'change': {'actions': actions}}]})
        counts = guard.inspect({'resource_changes': [{'address': 'aws_ecr_repository.api',
                                                      'change': {'actions': ['create']}}]})
        self.assertEqual(counts['create'], 1)

    def test_central_matrix_resolves_only_enabled_sources_and_rejects_bad_roles(self):
        deploy = module('deployment-matrix')
        registry = load_registry()
        config = {'mobile-api': {'publisher_role_arn': 'arn:aws:iam::123456789012:role/publish',
                                 'deployer_role_arn': 'arn:aws:iam::123456789012:role/deploy'}}
        seen = []
        def resolve(repository):
            seen.append(repository)
            return 'a' * 40
        result = deploy.matrix(registry, config, '123456789012', resolve)
        self.assertEqual(seen, ['KairosApplication/kairos-springboot'])
        self.assertEqual(result['include'][0]['source_sha'], 'a' * 40)
        self.assertEqual(len(result['include']), 1)
        with self.assertRaises(ValueError):
            deploy.matrix(registry, dict(config, **{'agent-api': config['mobile-api']}),
                          '123456789012', resolve)
        config['mobile-api']['deployer_role_arn'] = 'arn:aws:iam::999999999999:role/deploy'
        with self.assertRaises(ValueError):
            deploy.matrix(registry, config, '123456789012', resolve)

    def test_release_state_distinguishes_install_update_and_current(self):
        state = module('release-state')
        self.assertEqual(state.classify('desired', None, None), 'install')
        self.assertEqual(state.classify('desired', 'old', 'deployed'), 'update')
        self.assertEqual(state.classify('desired', 'desired', 'failed'), 'update')
        self.assertEqual(state.classify('desired\n', 'desired', 'deployed'), 'current')
