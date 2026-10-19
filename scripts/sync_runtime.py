"""Populate Secrets Manager via SDK, preserving existing values and masking all credentials."""
import json
import os
import secrets
from urllib.parse import quote
from pipeline_bootstrap import ensure_secret


def merge_runtime(existing, supplied, redis_url, internal_key):
    mobile = dict(existing, **supplied)
    for field in ("DB_URL", "DB_USERNAME", "DB_PASSWORD"):
        if not isinstance(mobile.get(field), str) or not mobile[field]:
            raise ValueError("Configure " + field + " no Secret RUNTIME_SECRETS_JSON ou no Secrets Manager.")
    mobile["REDIS_URL"] = redis_url
    mobile["KAIROS_INTERNAL_API_KEY"] = internal_key
    mobile.setdefault("AUTH_SIGNING_KEY", secrets.token_urlsafe(48))
    return mobile


def main():
    import boto3
    client = boto3.client("secretsmanager")
    cluster = os.environ["CLUSTER_NAME"]
    endpoint = os.environ["REDIS_ENDPOINT"]
    if not endpoint:
        raise ValueError("Endpoint Redis ausente.")
    password = client.get_secret_value(
        SecretId=f"kairos/automation/{cluster}/redis-auth")["SecretString"]
    internal = ensure_secret(client, f"kairos/automation/{cluster}/internal-key",
                             lambda: secrets.token_urlsafe(48))
    redis_url = "rediss://:" + quote(password, safe="") + "@" + endpoint + ":6379/0"
    try:
        existing = json.loads(client.get_secret_value(SecretId="kairos/production/mobile-api")["SecretString"])
    except client.exceptions.ResourceNotFoundException:
        existing = {}
    mobile = merge_runtime(existing, json.loads(os.environ.get("RUNTIME_SECRETS_JSON") or "{}"),
                           redis_url, internal)
    values = {"mobile-api": mobile,
              "redis-api": {"REDIS_URL": redis_url, "KAIROS_INTERNAL_API_KEY": internal}}
    for name, value in values.items():
        serialized = json.dumps(value, sort_keys=True)
        # ClientRequestToken deduplicates retries; no credentials are logged or passed in CLI args.
        import hashlib
        client.put_secret_value(SecretId="kairos/production/" + name,
            SecretString=serialized, ClientRequestToken=hashlib.sha256(serialized.encode()).hexdigest())
    print("Segredos runtime sincronizados sem expor valores.")


if __name__ == "__main__":
    main()
