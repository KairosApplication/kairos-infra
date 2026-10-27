"""Stable Redis password in Secrets Manager; ephemeral Terraform variable, never state."""
import os
import secrets
from pipeline_bootstrap import ensure_secret


def main():
    import boto3
    cluster = os.environ["CLUSTER_NAME"]
    value = ensure_secret(boto3.client("secretsmanager"), f"kairos/automation/{cluster}/redis-auth",
                          lambda: secrets.token_urlsafe(48))
    print("::add-mask::" + value)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
        stream.write("TF_VAR_redis_auth_token=" + value + "\n")


if __name__ == "__main__":
    main()
