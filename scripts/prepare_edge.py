"""Resolve the cluster-owned private ALB; never adopt unrelated AWS resources."""
import json
import os
import re
import time
from pathlib import Path


def select_origin(load_balancers, hostname, cluster, account, tags, allow_provisioning=False):
    if not re.fullmatch(r"internal-[a-zA-Z0-9-]+[.][a-z0-9-]+[.]elb[.]amazonaws[.]com", hostname):
        raise ValueError("Ingress ainda nao possui DNS de ALB privado valido.")
    matches = [lb for lb in load_balancers if lb["DNSName"] == hostname]
    if len(matches) != 1:
        raise ValueError("Nao foi encontrado um unico ALB para o Ingress.")
    lb = matches[0]
    if (lb["Scheme"] != "internal" or lb["Type"] != "application"
            or lb["State"]["Code"] not in (("active", "provisioning") if allow_provisioning else ("active",))
            or lb["LoadBalancerArn"].split(":")[4] != account
            or tags.get("eks:eks-cluster-name") != cluster):
        raise ValueError("ALB deve estar ativo, privado e pertencer a conta/cluster Kairos.")
    return lb


def resolve_origin(elb, hostname, cluster, account, attempts=60, delay=10):
    # Ingress DNS can appear before the ALB is active. Retry only that
    # transitional state; never retry ownership or permission failures.
    for attempt in range(attempts):
        lbs = [lb for page in elb.get_paginator("describe_load_balancers").paginate()
               for lb in page["LoadBalancers"]]
        matching = [lb for lb in lbs if lb["DNSName"] == hostname]
        if len(matching) != 1:
            raise ValueError("ALB nao encontrado ou ambiguo.")
        tags = {tag["Key"]: tag["Value"] for tag in elb.describe_tags(
            ResourceArns=[matching[0]["LoadBalancerArn"]])["TagDescriptions"][0]["Tags"]}
        lb = select_origin(lbs, hostname, cluster, account, tags, allow_provisioning=True)
        if lb["State"]["Code"] == "active":
            return lb
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise TimeoutError("ALB privado nao ficou ativo dentro do prazo.")


def main():
    import boto3
    env = os.environ
    elb = boto3.client("elbv2")
    ingresses = json.loads(Path(env["RUNNER_TEMP"], "api-ingresses.json").read_text())
    from registry import load_registry
    enabled = {name for name,item in load_registry().items() if item["enabled"]}
    if not ingresses or set(ingresses) - (enabled & {"mobile-api", "agent-api"}):
        raise ValueError("Origens CloudFront invalidas.")
    origins = {}
    for name,ingress in ingresses.items():
        hostname = ingress["status"]["loadBalancer"]["ingress"][0]["hostname"]
        lb = resolve_origin(elb, hostname, env["EKS_CLUSTER_NAME"], env["AWS_ACCOUNT_ID"])
        origins[name] = {"arn": lb["LoadBalancerArn"], "dns": hostname}
    values = {"aws_region": env["AWS_REGION"], "aws_account_id": env["AWS_ACCOUNT_ID"],
              "cluster_name": env["EKS_CLUSTER_NAME"], "origins": origins}
    temporary = Path(env["RUNNER_TEMP"])
    (temporary / "edge.tfvars.json").write_text(json.dumps(values), encoding="utf-8")
    bucket = env["TF_STATE_BUCKET"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise ValueError("Bucket de estado invalido.")
    (temporary / "edge-backend.hcl").write_text(
        f'bucket = "{bucket}"\nkey = "production/cloudfront.tfstate"\n'
        f'region = "{env["AWS_REGION"]}"\nencrypt = true\nuse_lockfile = true\n', encoding="utf-8")


if __name__ == "__main__":
    main()
