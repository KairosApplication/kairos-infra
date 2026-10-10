"""Dispatch each enabled source repository's deploy workflow using a GitHub App."""
import json
import os
import urllib.request
from registry import load_registry


if __name__ == '__main__':
    failures = []
    for name, service in load_registry().items():
        if not service['enabled']:
            continue
        repository = service['source_repository']
        request = urllib.request.Request(
            f'https://api.github.com/repos/{repository}/actions/workflows/deploy.yml/dispatches',
            data=json.dumps({'ref': 'main'}).encode(), method='POST',
            headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                     'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 204:
                    raise RuntimeError('Resposta inesperada do GitHub.')
            print(f'Deploy solicitado: {name} ({repository}). Acompanhe a execucao no repo de origem.')
        except Exception:
            failures.append(repository)
            print(f'Falha ao solicitar deploy de {repository}; verifique instalacao do App e deploy.yml.')
    if failures:
        raise SystemExit('Um ou mais deploys nao puderam ser solicitados.')
