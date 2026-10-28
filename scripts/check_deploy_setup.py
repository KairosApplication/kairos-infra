"""Validate orchestration prerequisites without making AWS calls or reading key values."""
import os
import re

from pipeline_bootstrap import validate


def check(env):
    # Reuses repository/main, JSON, CIDR, service and certificate configuration validation.
    validate(env)
    access_key = env.get("HAS_AWS_ACCESS_KEY_ID") == "true"
    secret_key = env.get("HAS_AWS_SECRET_ACCESS_KEY") == "true"
    session_token = env.get("HAS_AWS_SESSION_TOKEN") == "true"
    if access_key != secret_key:
        raise ValueError("Configure o par AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY, ou use OIDC.")
    role = env.get("AWS_BOOTSTRAP_ROLE_ARN", "")
    if not access_key and not role:
        raise ValueError("Configure AWS_BOOTSTRAP_ROLE_ARN para OIDC ou o par de Secrets AWS.")
    if session_token and not access_key:
        raise ValueError("AWS_SESSION_TOKEN exige tambem o par de Secrets AWS.")
    account = env["AWS_ACCOUNT_ID"]
    if role and not re.fullmatch(rf"arn:aws:iam::{account}:role/[A-Za-z0-9_+=,.@/-]+", role):
        raise ValueError("AWS_BOOTSTRAP_ROLE_ARN deve ser uma role IAM da conta configurada.")
    principal = env.get("AWS_STATIC_PRINCIPAL_ARN", "")
    if access_key and role and not principal:
        raise ValueError("Com chaves e bootstrap role, configure AWS_STATIC_PRINCIPAL_ARN.")
    if principal and not re.fullmatch(rf"arn:aws:iam::{account}:(user|role)/[A-Za-z0-9_+=,.@/-]+", principal):
        raise ValueError("AWS_STATIC_PRINCIPAL_ARN deve pertencer a conta configurada.")
    if not env["RUNNER_APP_ID"].isdigit():
        raise ValueError("RUNNER_APP_ID deve conter o ID numerico do GitHub App.")


def main():
    try:
        check(os.environ)
    except (ValueError, TypeError, KeyError):
        # Deliberately omit raw exceptions: invalid operator input may contain credentials.
        # Field-level validation is exercised through pure check() unit tests.
        print("Configuracao de deploy incompleta ou invalida. Consulte docs/deploy-apis.md.")
        raise SystemExit(1)
    print("Configuracao estrutural validada. Acesso e recursos AWS serao verificados no deploy.")


if __name__ == "__main__":
    main()
