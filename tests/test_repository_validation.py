"""Keep plain YAML validation separate from Helm's rendered-manifest checks."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('repository_validation', ROOT / '.github/scripts/validate.py')
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class RepositoryValidationTests(unittest.TestCase):
    def test_unrendered_chart_templates_are_deferred(self):
        template = ROOT / 'charts/kairos-api/templates/configmap.yaml'
        self.assertTrue(template.is_file())
        self.assertFalse(VALIDATOR.validate_file(template))

    def test_nested_chart_templates_are_deferred(self):
        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory) / 'example'
            template = chart / 'templates/nested/deployment.yaml'
            template.parent.mkdir(parents=True)
            (chart / 'Chart.yaml').write_text('apiVersion: v2\nname: example\nversion: 0.1.0\n')
            template.write_text('metadata:\n  name: {{ include "example.name" . }}-config\n')
            self.assertFalse(VALIDATOR.validate_file(template))

    def test_chart_metadata_values_and_environment_files_are_validated(self):
        for path in ('charts/kairos-api/Chart.yaml', 'charts/kairos-api/values.yaml',
                     'environments/production/mobile-api.yaml'):
            with self.subTest(path=path):
                self.assertTrue(VALIDATOR.validate_file(ROOT / path))

    def test_invalid_plain_yaml_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for relative in ('values.yaml', 'templates/not-a-chart.yaml', 'environments/production.yaml'):
                with self.subTest(path=relative):
                    path = Path(directory) / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('invalid: [\n')
                    with self.assertRaises(yaml.YAMLError):
                        VALIDATOR.validate_file(path)


if __name__ == '__main__':
    unittest.main()
