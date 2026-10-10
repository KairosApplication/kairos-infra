"""Generate non-secret backend and tfvars files for CI; one service registry."""
import json
import os
import re
from pathlib import Path
from registry import load_registry, terraform_services


def configuration(config, registry, account, region, bucket):
    if not re.fullmatch(r'[0-9]{12}', account):
        raise ValueError('AWS_ACCOUNT_ID invalido.')
    if not re.fullmatch(r'[a-z]{2}-[a-z]+-[0-9]', region):
        raise ValueError('AWS_REGION invalida.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise ValueError('TF_STATE_BUCKET invalido.')
    allowed = {'cluster_name', 'kubernetes_version', 'vpc_cidr', 'single_nat_gateway',
               'cluster_public_access_cidrs', 'cluster_admin_principal_arns',
               'github_oidc_provider_arn', 'provision_deployment_runner',
               'deployment_runner_ami_id', 'github_static_principal_arns'}
    if set(config) - allowed:
        raise ValueError('INFRA_CONFIG_JSON possui campos desconhecidos; services vem do cadastro.')
    if not config.get('cluster_admin_principal_arns') or not config.get('cluster_public_access_cidrs'):
        raise ValueError('Configure administradores e CIDRs de acesso ao cluster.')
    return dict(config, aws_account_id=account, aws_region=region,
                services=terraform_services(registry))


if __name__ == '__main__':
    config = configuration(json.loads(os.environ['INFRA_CONFIG_JSON']), load_registry(),
                           os.environ['AWS_ACCOUNT_ID'], os.environ['AWS_REGION'],
                           os.environ['TF_STATE_BUCKET'])
    output = Path(os.environ['RUNNER_TEMP'])
    (output / 'infra.tfvars.json').write_text(json.dumps(config), encoding='utf-8')
    backend = {'bucket': os.environ['TF_STATE_BUCKET'],
               'key': 'production/terraform.tfstate', 'region': os.environ['AWS_REGION'],
               'encrypt': True, 'use_lockfile': True}
    (output / 'backend.hcl').write_text('\n'.join(
        f'{key} = {json.dumps(value)}' for key, value in backend.items()), encoding='utf-8')
