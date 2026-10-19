"""Bootstrap state and scoped workflow roles. Initial AWS credentials are supplied by the operator."""
import json
import os
import re
import time
from pathlib import Path

REPOSITORY = "KairosApplication/kairos-infra"


def role_names(cluster, account):
    return {key: f"arn:aws:iam::{account}:role/{cluster}-infra-{key}"
            for key in ("plan", "apply", "platform")}


def validate(env):
    required = ("AWS_ACCOUNT_ID", "AWS_REGION", "TF_STATE_BUCKET", "INFRA_CONFIG_JSON",
                "DEPLOY_CONFIG_JSON", "RUNNER_APP_ID", "RUNNER_APP_PRIVATE_KEY")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise ValueError("Configure no kairos-infra: " + ", ".join(missing))
    if env.get("GITHUB_REPOSITORY") != REPOSITORY or env.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("O fluxo completo executa somente na main do kairos-infra.")
    if not re.fullmatch(r"[0-9]{12}", env["AWS_ACCOUNT_ID"]):
        raise ValueError("AWS_ACCOUNT_ID invalido.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", env["TF_STATE_BUCKET"]):
        raise ValueError("Use bucket de estado sem pontos, letras minusculas e hifens.")
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]", env["AWS_REGION"]):
        raise ValueError("AWS_REGION invalida.")
    config = json.loads(env["INFRA_CONFIG_JSON"])
    cluster = config.setdefault("cluster_name", "kairos-production")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", cluster):
        raise ValueError("Nome do cluster invalido.")
    if not config.get("cluster_public_access_cidrs"):
        raise ValueError("Configure cluster_public_access_cidrs com seu IP /32.")
    # Apply the same allowlist and CIDR/admin validation used by Terraform inputs.
    import ipaddress
    for cidr in config.get("cluster_public_access_cidrs", []):
        network = ipaddress.ip_network(cidr, strict=False)
        if network.version != 4 or network.prefixlen == 0:
            raise ValueError("Configure CIDRs IPv4 restritos, nunca 0.0.0.0/0.")
    deploy = json.loads(env["DEPLOY_CONFIG_JSON"])
    public = deploy.get("mobile-api", {})
    if not public.get("api_host") or not public.get("certificate_arn"):
        raise ValueError("Configure api_host e certificate_arn validados para mobile-api.")
    expected_prefix = f"arn:aws:acm:{env['AWS_REGION']}:{env['AWS_ACCOUNT_ID']}:certificate/"
    if not public["certificate_arn"].startswith(expected_prefix):
        raise ValueError("Certificado deve pertencer a mesma conta/regiao do ALB.")
    if not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", public["api_host"]):
        raise ValueError("api_host invalido, informe somente o dominio.")
    if config.get("provision_redis", True) is not True:
        raise ValueError("O fluxo completo provisiona Redis. Para Redis externo, usar o fluxo avancado.")
    if config.get("redis_auth_version", 1) != 1:
        raise ValueError("Rotacao Redis exige procedimento separado; o fluxo usa versao 1.")
    config["provision_redis"] = True
    config["provision_deployment_runner"] = True
    from registry import load_registry
    import importlib.util
    spec = importlib.util.spec_from_file_location("prepare_infra", Path(__file__).with_name("prepare-infra.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = dict(config, cluster_admin_principal_arns=config.get("cluster_admin_principal_arns") or [
        role_names(cluster, env["AWS_ACCOUNT_ID"])["platform"]])
    module.configuration(checks, load_registry(), env["AWS_ACCOUNT_ID"], env["AWS_REGION"], env["TF_STATE_BUCKET"])
    return config, deploy


def trust(provider, subject, principal=None):
    statements = [{"Effect": "Allow", "Principal": {"Federated": provider},
                   "Action": "sts:AssumeRoleWithWebIdentity",
                   "Condition": {"StringEquals": {
                       "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                       "token.actions.githubusercontent.com:sub": f"repo:{REPOSITORY}:{subject}"}}}]
    if principal:
        statements.append({"Effect": "Allow", "Principal": {"AWS": principal},
                           "Action": "sts:AssumeRole"})
    return {"Version": "2012-10-17", "Statement": statements}


def policies(account, region, bucket, cluster):
    state = [{"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
              "Resource": f"arn:aws:s3:::{bucket}"},
             {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
              "Resource": f"arn:aws:s3:::{bucket}/production/terraform.tfstate"},
             {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
              "Resource": f"arn:aws:s3:::{bucket}/production/terraform.tfstate.tflock"}]
    read = ["ec2:Describe*", "eks:Describe*", "eks:List*", "iam:Get*", "iam:List*",
            "ecr:Describe*", "ecr:List*", "ecr:GetRepositoryPolicy", "logs:Describe*",
            "logs:List*", "secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy",
            "secretsmanager:ListSecrets", "elasticache:Describe*", "elasticache:ListTagsForResource",
            "sts:GetCallerIdentity"]
    write = ["ec2:*", "eks:*", "ecr:*", "logs:*", "elasticache:*",
             "secretsmanager:CreateSecret", "secretsmanager:DescribeSecret",
             "secretsmanager:TagResource", "secretsmanager:UntagResource",
             "secretsmanager:UpdateSecret", "secretsmanager:DeleteSecret",
             "secretsmanager:GetResourcePolicy", "secretsmanager:PutResourcePolicy",
             "secretsmanager:DeleteResourcePolicy"]
    iam_resources = [f"arn:aws:iam::{account}:role/{cluster}-*",
                     f"arn:aws:iam::{account}:instance-profile/{cluster}-*"]
    service_linked = {"Effect": "Allow", "Action": "iam:CreateServiceLinkedRole", "Resource": "*",
                      "Condition": {"StringEquals": {"iam:AWSServiceName":
                          ["eks.amazonaws.com", "eks-nodegroup.amazonaws.com", "elasticache.amazonaws.com", "spot.amazonaws.com"]}}}
    apply = state + [service_linked,{"Effect": "Allow", "Action": read + write, "Resource": "*"},
                     {"Effect": "Allow", "Action": ["iam:*"], "Resource": iam_resources}]
    platform = [{"Effect": "Allow", "Action": ["eks:DescribeCluster"],
                 "Resource": f"arn:aws:eks:{region}:{account}:cluster/{cluster}"}]
    redis_password = {"Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"],
                      "Resource": f"arn:aws:secretsmanager:{region}:{account}:secret:kairos/automation/{cluster}/redis-auth-*"}
    state = state + [redis_password]
    apply = apply + [redis_password]
    return {key: {"Version": "2012-10-17", "Statement": statements}
            for key, statements in {
                "plan": state + [{"Effect": "Allow", "Action": read, "Resource": "*"}],
                "apply": apply, "platform": platform}.items()}


def current_principal(sts, iam):
    arn = sts.get_caller_identity()["Arn"]
    if ":assumed-role/" in arn:
        return iam.get_role(RoleName=arn.split(":assumed-role/")[1].split("/")[0])["Role"]["Arn"]
    if ":user/" in arn:
        return arn
    raise ValueError("Use usuario/role IAM dedicado; nao use a conta root.")


def prepare_bucket(s3, bucket, region, account):
    try:
        s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    except s3.exceptions.ClientError as error:
        if str(error.response["Error"]["Code"]) not in ("404", "NoSuchBucket"):
            raise
        args = {"Bucket": bucket}
        if region != "us-east-1":
            args["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**args)
        s3.get_waiter("bucket_exists").wait(Bucket=bucket)
    actual = s3.get_bucket_location(Bucket=bucket, ExpectedBucketOwner=account)["LocationConstraint"] or "us-east-1"
    if actual != region:
        raise ValueError("O bucket de estado pertence a outra regiao.")
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        key: True for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")})
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
    # Preserve existing statements; enforce TLS without replacing unrelated policy.
    try:
        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
    except s3.exceptions.ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchBucketPolicy":
            raise
        policy = {"Version": "2012-10-17", "Statement": []}
    policy["Statement"] = [s for s in policy["Statement"] if s.get("Sid") != "KairosRequireTLS"]
    policy["Statement"].append({"Sid": "KairosRequireTLS", "Effect": "Deny", "Principal": "*",
        "Action": "s3:*", "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
        "Condition": {"Bool": {"aws:SecureTransport": "false"}}})
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))


def ensure_secret(client, name, generate):
    try:
        return client.get_secret_value(SecretId=name)["SecretString"]
    except client.exceptions.ResourceNotFoundException:
        value = generate()
        client.create_secret(Name=name, SecretString=value,
                             Tags=[{"Key": "Project", "Value": "Kairos"}])
        return value


def main():
    import boto3
    from registry import load_registry
    from prepare_full import prepare
    env = os.environ
    config, deploy = validate(env)
    account, region, bucket = env["AWS_ACCOUNT_ID"], env["AWS_REGION"], env["TF_STATE_BUCKET"]
    sts, iam = boto3.client("sts"), boto3.client("iam")
    if sts.get_caller_identity()["Account"] != account:
        raise ValueError("Credencial AWS pertence a outra conta.")
    principal = None
    if env.get("STATIC_AUTH") == "true":
        principal = env.get("AWS_STATIC_PRINCIPAL_ARN") or current_principal(sts, iam)
        if env.get("AWS_BOOTSTRAP_ROLE_ARN") and not env.get("AWS_STATIC_PRINCIPAL_ARN"):
            raise ValueError("Configure AWS_STATIC_PRINCIPAL_ARN para as chaves que assumirao as roles.")
        if not re.fullmatch(rf"arn:aws:iam::{account}:(user|role)/[A-Za-z0-9_+=,.@/-]+", principal):
            raise ValueError("Principal estatico invalido ou de outra conta.")
    # Check the external database credentials before provisioning any infrastructure.
    supplied = json.loads(env.get("RUNTIME_SECRETS_JSON") or "{}")
    secret_client = boto3.client("secretsmanager")
    try:
        previous = json.loads(secret_client.get_secret_value(
            SecretId="kairos/production/mobile-api")["SecretString"])
    except secret_client.exceptions.ResourceNotFoundException:
        previous = {}
    database = dict(previous, **supplied)
    if any(not database.get(field) for field in ("DB_URL", "DB_USERNAME", "DB_PASSWORD")):
        raise ValueError("Configure DB_URL, DB_USERNAME e DB_PASSWORD no Secret RUNTIME_SECRETS_JSON antes de iniciar.")
    public = deploy["mobile-api"]
    certificate = boto3.client("acm").describe_certificate(CertificateArn=public["certificate_arn"])["Certificate"]
    if certificate["Status"] != "ISSUED":
        raise ValueError("O certificado ACM ainda nao foi validado.")
    host = public["api_host"]
    if not any(host == name or (name.startswith("*.") and host.split(".", 1)[-1] == name[2:])
               for name in certificate["SubjectAlternativeNames"]):
        raise ValueError("Certificado ACM nao cobre api_host.")
    provider = config.get("github_oidc_provider_arn")
    if not provider:
        providers = iam.list_open_id_connect_providers()["OpenIDConnectProviderList"]
        provider = next((p["Arn"] for p in providers if p["Arn"].endswith("/token.actions.githubusercontent.com")), None)
        if not provider:
            provider = iam.create_open_id_connect_provider(
                Url="https://token.actions.githubusercontent.com",
                ClientIDList=["sts.amazonaws.com"],
                Tags=[{"Key": "Project", "Value": "Kairos"}])["OpenIDConnectProviderArn"]
    config["github_oidc_provider_arn"] = provider
    roles = role_names(config["cluster_name"], account)
    prepare_bucket(boto3.client("s3"), bucket, region, account)
    for key, policy in policies(account, region, bucket, config["cluster_name"]).items():
        name = roles[key].split("/")[-1]
        subject = "environment:infrastructure-plan" if key == "plan" else "environment:infrastructure-production"
        document = json.dumps(trust(provider, subject, principal))
        try:
            iam.get_role(RoleName=name)
        except iam.exceptions.NoSuchEntityException:
            iam.create_role(RoleName=name, AssumeRolePolicyDocument=document,
                            Tags=[{"Key": "Project", "Value": "Kairos"}])
        else:
            iam.update_assume_role_policy(RoleName=name, PolicyDocument=document)
        iam.put_role_policy(RoleName=name, PolicyName="KairosWorkflow", PolicyDocument=json.dumps(policy))
    config["cluster_admin_principal_arns"] = sorted(set(config.get("cluster_admin_principal_arns", []) + [roles["platform"]]))
    if principal:
        config["github_static_principal_arns"] = {
            name: principal for name, item in load_registry().items() if item["enabled"]}
    if not config.get("deployment_runner_ami_id"):
        config["deployment_runner_ami_id"] = boto3.client("ssm").get_parameter(
            Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64")["Parameter"]["Value"]
    import secrets
    ensure_secret(boto3.client("secretsmanager"),
                  f"kairos/automation/{config['cluster_name']}/redis-auth",
                  lambda: secrets.token_urlsafe(48))
    prepare(config, deploy, roles)
    # IAM propagation before the next job assumes a newly created role.
    time.sleep(15)
    print("Bucket e roles preparados. Nenhuma credencial foi escrita nos outputs.")


if __name__ == "__main__":
    main()
