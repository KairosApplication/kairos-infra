"""Populate Secrets Manager via SDK, preserving existing values and masking all credentials."""
import json
import base64
import os
import re
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
    if "AUTH_SIGNING_KEY" not in mobile:
        mobile["AUTH_SIGNING_KEY"] = base64.b64encode(secrets.token_bytes(48)).decode("ascii")
    else:
        key = mobile["AUTH_SIGNING_KEY"]
        # Legacy bootstrap generated 48 bytes as 64 URL-safe characters.
        # Java's Base64.getDecoder() requires the standard alphabet. Translate
        # only that legacy format, preserving the signing bytes and valid keys.
        if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{64}", key):
            mobile["AUTH_SIGNING_KEY"] = key.translate(str.maketrans("-_", "+/"))
    return mobile


def parse_agent_input(raw):
    """Accept an operator-pasted MongoDB URI or the documented runtime JSON."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw.startswith(("mongodb://", "mongodb+srv://")):
        # The API repository documents kairos_ai as the verified application database.
        from urllib.parse import urlsplit
        try:
            database = urlsplit(raw).path.lstrip("/").split("/", 1)[0] or "kairos_ai"
        except ValueError:
            raise ValueError("URI MongoDB invalida no Secret da API de IA.") from None
        return {"MONGODB_URI": raw, "MONGODB_DATABASE": database}
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) - {"MONGODB_URI", "MONGODB_DATABASE", "API_ACCESS_TOKEN"}:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ValueError("Secret da API de IA deve conter URI MongoDB ou JSON de runtime valido.") from None


def merge_agent_runtime(existing, supplied, generated_token):
    value = dict(existing, **supplied)
    uri = value.get("MONGODB_URI", "")
    if not isinstance(uri, str) or not uri.startswith(("mongodb://", "mongodb+srv://")):
        raise ValueError("Configure MONGODB_URI no Secret AGENT_RUNTIME_SECRETS_JSON.")
    from urllib.parse import urlsplit, parse_qs
    try:
        parsed = urlsplit(uri)
        query = {key.lower(): [v.lower() for v in values] for key, values in parse_qs(parsed.query).items()}
        if not parsed.hostname or any("false" in query.get(key, []) for key in ("tls", "ssl")) or any(
                "true" in query.get(key, []) for key in ("tlsinsecure", "tlsallowinvalidcertificates", "tlsallowinvalidhostnames")):
            raise ValueError()
    except ValueError:
        raise ValueError("Conexao MongoDB invalida ou com protecoes TLS desativadas.") from None
    database = value.get("MONGODB_DATABASE") or urlsplit(uri).path.lstrip("/").split("/", 1)[0]
    if not database or not isinstance(database, str):
        raise ValueError("Configure MONGODB_DATABASE com o banco real da API de IA.")
    value["MONGODB_DATABASE"] = database
    value.setdefault("API_ACCESS_TOKEN", generated_token)
    if not isinstance(value["API_ACCESS_TOKEN"], str) or len(value["API_ACCESS_TOKEN"]) < 32:
        raise ValueError("API_ACCESS_TOKEN deve possuir ao menos 32 caracteres.")
    return value


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
    from registry import load_registry
    if load_registry().get("agent-api", {}).get("enabled"):
        try:
            previous_agent = json.loads(client.get_secret_value(SecretId="kairos/production/agent-api")["SecretString"])
        except client.exceptions.ResourceNotFoundException:
            previous_agent = {}
        agent_token = ensure_secret(client, f"kairos/automation/{cluster}/agent-api-key",
                                    lambda: secrets.token_urlsafe(48))
        values["agent-api"] = merge_agent_runtime(previous_agent,
            parse_agent_input(os.environ.get("AGENT_RUNTIME_SECRETS_JSON")), agent_token)
    for name, value in values.items():
        serialized = json.dumps(value, sort_keys=True)
        # ClientRequestToken deduplicates retries; no credentials are logged or passed in CLI args.
        import hashlib
        client.put_secret_value(SecretId="kairos/production/" + name,
            SecretString=serialized, ClientRequestToken=hashlib.sha256(serialized.encode()).hexdigest())
    print("Segredos runtime sincronizados sem expor valores.")


if __name__ == "__main__":
    main()
