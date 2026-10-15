"""Resolve only registered APIs at their current main commit; no remote dispatch."""
import json
import os
import re
import urllib.request
from registry import load_registry


def latest(repository):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/commits/main",
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["sha"]


def matrix(registry, config, account, resolve=latest):
    if not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("AWS_ACCOUNT_ID deve ter 12 digitos.")
    enabled = {name: item for name, item in registry.items() if item["enabled"]}
    if set(config) != set(enabled):
        raise ValueError("DEPLOY_CONFIG_JSON deve configurar exatamente os servicos habilitados.")
    entries = []
    for name, item in enabled.items():
        values = config[name]
        if set(values) - {"publisher_role_arn", "deployer_role_arn", "api_host", "certificate_arn"}:
            raise ValueError("Campo desconhecido na configuracao de deploy.")
        for key in ("publisher_role_arn", "deployer_role_arn"):
            if not re.fullmatch(rf"arn:aws:iam::{account}:role/[A-Za-z0-9_+=,.@/-]+", values.get(key, "")):
                raise ValueError("Role ausente ou de outra conta.")
        sha = resolve(item["source_repository"])
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("Commit main invalido.")
        entries.append({"service": name, "source_repository": item["source_repository"],
                        "source_sha": sha,
                        "publisher_role_arn": values["publisher_role_arn"],
                        "deployer_role_arn": values["deployer_role_arn"],
                        "api_host": values.get("api_host", ""),
                        "certificate_arn": values.get("certificate_arn", "")})
    return {"include": entries}


if __name__ == "__main__":
    result = matrix(load_registry(), json.loads(os.environ["DEPLOY_CONFIG_JSON"]),
                    os.environ["AWS_ACCOUNT_ID"])
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write("matrix=" + json.dumps(result) + "\n")
    print(json.dumps(result, indent=2))
