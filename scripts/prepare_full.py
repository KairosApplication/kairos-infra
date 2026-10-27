"""Write non-secret full-pipeline configuration and GitHub outputs."""
import json
import os
from pathlib import Path
from registry import load_registry
from pipeline_bootstrap import role_names


def prepare(config, deploy, roles=None):
    registry = load_registry()
    account = os.environ["AWS_ACCOUNT_ID"]
    cluster = config["cluster_name"]
    roles = roles or role_names(cluster, account)
    enabled = {name: item for name, item in registry.items() if item["enabled"]}
    if set(deploy) - set(enabled):
        raise ValueError("DEPLOY_CONFIG_JSON contem servicos nao cadastrados.")
    resolved = {}
    for name in enabled:
        values = deploy.get(name, {})
        resolved[name] = dict(values,
            publisher_role_arn=f"arn:aws:iam::{account}:role/{cluster}-{name}-publish",
            deployer_role_arn=f"arn:aws:iam::{account}:role/{cluster}-{name}-deploy")
    output = {"config": json.dumps(config), "deploy_config": json.dumps(resolved),
              "cluster": cluster, **{f"{key}_role": arn for key, arn in roles.items()}}
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        for key, value in output.items():
            stream.write(f"{key}={value}\n")
    Path(os.environ["RUNNER_TEMP"], "full-infra.json").write_text(json.dumps(config), encoding="utf-8")
