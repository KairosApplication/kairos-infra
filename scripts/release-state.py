"""Classify a Helm release as install, update, or already current.

Always reconcile live drift with Helm afterwards; comparison is for reporting.
"""
import argparse
import os
import subprocess
from pathlib import Path


def classify(desired, current, status):
    if current is None:
        return 'install'
    if status != 'deployed' or desired.strip() != current.strip():
        return 'update'
    return 'current'


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--values', required=True)
    parser.add_argument('--overrides', required=True)
    args = parser.parse_args()
    desired = subprocess.run(['helm', 'template', args.release, 'charts/kairos-api',
                              '--namespace', args.namespace, '-f', args.values,
                              '-f', args.overrides], check=True, text=True, capture_output=True).stdout
    status = subprocess.run(['helm', 'status', args.release, '--namespace', args.namespace,
                             '--output', 'json'], text=True, capture_output=True)
    current = None
    state = None
    if status.returncode:
        if 'release: not found' not in status.stderr.lower():
            raise SystemExit('Nao foi possivel consultar o release: verifique acesso ao cluster.')
    else:
        state = json.loads(status.stdout)['info']['status']
        current = subprocess.run(['helm', 'get', 'manifest', args.release,
                                  '--namespace', args.namespace], check=True,
                                 text=True, capture_output=True).stdout
    action = classify(desired, current, state)
    print(f'Estado da aplicacao: {action}. Helm reconciliara tambem eventuais desvios no cluster.')
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'action={action}\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as output:
            output.write(f'### {args.release}: {action}\n')
