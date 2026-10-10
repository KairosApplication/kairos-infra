"""Validate the deployment allowlist and generate Terraform services from it."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_registry(path=None):
    data = json.loads(Path(path or ROOT / 'services.json').read_text(encoding='utf-8'))
    namespaces, repositories = set(), set()
    for name, item in data.items():
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,38}[a-z0-9]', name):
            raise ValueError('Nome de servico invalido.')
        if not isinstance(item.get('enabled'), bool):
            raise ValueError('enabled deve ser booleano.')
        if not item['enabled']:
            continue
        namespace = item.get('namespace', '')
        repository = item.get('source_repository', '')
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]', namespace):
            raise ValueError('Namespace invalido.')
        if not re.fullmatch(r'KairosApplication/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Repositorio deve pertencer a KairosApplication.')
        if namespace in namespaces or repository.lower() in repositories:
            raise ValueError('Cada servico deve ter namespace e repositorio exclusivos.')
        namespaces.add(namespace)
        repositories.add(repository.lower())
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,51}[a-z0-9]', item.get('release', '')):
            raise ValueError('Nome Helm invalido.')
        if item.get('ecr_repository') != f'kairos/{name}':
            raise ValueError('ECR deve corresponder ao nome do servico.')
        if item.get('build_kind', 'docker') not in ('java21', 'docker'):
            raise ValueError('build_kind deve ser java21 ou docker.')
        for field in ('values', 'fallback_dockerfile'):
            value = item.get(field)
            if field == 'fallback_dockerfile' and value is None:
                continue
            if not isinstance(value, str) or '\n' in value or '\r' in value:
                raise ValueError('Caminho de arquivo invalido.')
            target = (ROOT / value).resolve()
            if not target.is_relative_to(ROOT.resolve()) or not target.is_file():
                raise ValueError('Arquivo do servico ausente ou fora do repositorio.')
    if not namespaces:
        raise ValueError('Habilite pelo menos um servico.')
    return data


def terraform_services(registry):
    return {name: {'namespace': item['namespace'],
                   'github_repository': item['source_repository']}
            for name, item in registry.items() if item['enabled']}


if __name__ == '__main__':
    print(json.dumps(terraform_services(load_registry()), indent=2))
