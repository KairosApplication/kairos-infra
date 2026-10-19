"""Register a dedicated repository runner through SSM without secrets in command history."""
import base64
import hashlib
import json
import os
import re
import time
import urllib.request


def github(path, data=None):
    request = urllib.request.Request("https://api.github.com/repos/KairosApplication/kairos-infra" + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Authorization": "Bearer " + os.environ["RUNNER_GH_TOKEN"],
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def remote_script(url, digest, parameter, region, name):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Checksum ausente para o pacote oficial do runner.")
    if not url.startswith("https://github.com/actions/runner/releases/download/"):
        raise ValueError("Download do runner fora do repositorio oficial.")
    # No token is placed in this script or in the Run Command parameters.
    return f"""#!/bin/bash
set -euo pipefail
cloud-init status --wait >/dev/null
install -d -o kairos-runner -g kairos-runner -m 700 /opt/kairos-runner
cd /opt/kairos-runner
if [ -f svc.sh ]; then ./svc.sh stop || true; ./svc.sh uninstall || true; fi
curl --fail --silent --show-error --location '{url}' -o /tmp/kairos-runner.tar.gz
echo '{digest}  /tmp/kairos-runner.tar.gz' | sha256sum --check -
tar -xzf /tmp/kairos-runner.tar.gz
rm /tmp/kairos-runner.tar.gz
rm -f .runner .credentials .credentials_rsaparams
chown -R kairos-runner:kairos-runner /opt/kairos-runner
python3 - <<'PY'
import json, subprocess
token = subprocess.check_output(['aws', 'ssm', 'get-parameter', '--region', '{region}',
    '--name', '{parameter}', '--with-decryption', '--query', 'Parameter.Value', '--output', 'text'],
    text=True).strip()
try:
    subprocess.run(['runuser', '-u', 'kairos-runner', '--', './config.sh', '--unattended',
        '--url', 'https://github.com/KairosApplication/kairos-infra', '--token', token,
        '--name', '{name}', '--labels', 'kairos-eks', '--work', '_work'],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
finally:
    del token
PY
./svc.sh install kairos-runner
./svc.sh start
"""


def main():
    import boto3
    instance = os.environ["RUNNER_INSTANCE_ID"]
    if not re.fullmatch(r"i-[a-f0-9]+", instance):
        raise ValueError("Runner instance id invalido.")
    region = os.environ["AWS_REGION"]
    name = "kairos-" + instance
    runners = github("/actions/runners?per_page=100")["runners"]
    if any(r["name"] == name and r["status"] == "online" for r in runners):
        print("Runner dedicado ja esta online.")
        return
    ssm = boto3.client("ssm")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        info = ssm.describe_instance_information(Filters=[{"Key": "InstanceIds", "Values": [instance]}])
        if any(i["PingStatus"] == "Online" for i in info["InstanceInformationList"]):
            break
        time.sleep(10)
    else:
        raise RuntimeError("Runner nao se conectou ao SSM em 10 minutos.")
    # Registration token expires in an hour and is removed from SSM after configuration.
    token = github("/actions/runners/registration-token", {})["token"]
    parameter = f"/kairos/runner/{instance}/registration"
    ssm.put_parameter(Name=parameter, Value=token, Type="SecureString", Overwrite=True)
    del token
    try:
        for runner in runners:
            if runner["name"] == name:
                request = urllib.request.Request(
                    "https://api.github.com/repos/KairosApplication/kairos-infra/actions/runners/" + str(runner["id"]),
                    method="DELETE", headers={"Authorization": "Bearer " + os.environ["RUNNER_GH_TOKEN"],
                        "Accept": "application/vnd.github+json"})
                urllib.request.urlopen(request, timeout=30).close()
        package = next(p for p in github("/actions/runners/downloads") if p["os"] == "linux" and p["architecture"] == "x64")
        digest = package.get("sha256_checksum")
        if not digest:
            # GitHub.com can omit checksums in the runner-download endpoint.
            # Release asset digests are issued by GitHub for uploaded assets.
            tag = package["download_url"].split("/download/")[1].split("/")[0]
            request = urllib.request.Request(
                "https://api.github.com/repos/actions/runner/releases/tags/" + tag,
                headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                release = json.load(response)
            asset = next(a for a in release["assets"] if a["name"] == package["filename"])
            digest = (asset.get("digest") or "").removeprefix("sha256:")
        script = remote_script(package["download_url"], digest,
                               parameter, region, name)
        encoded = base64.b64encode(script.encode()).decode()
        command = ssm.send_command(InstanceIds=[instance], DocumentName="AWS-RunShellScript",
            Parameters={"commands": [f"echo '{encoded}' | base64 -d | bash"], "executionTimeout": ["600"]},
            TimeoutSeconds=600)["Command"]["CommandId"]
        deadline = time.monotonic() + 660
        while time.monotonic() < deadline:
            try:
                result = ssm.get_command_invocation(CommandId=command, InstanceId=instance)
            except ssm.exceptions.InvocationDoesNotExist:
                time.sleep(5)
                continue
            if result["Status"] == "Success":
                break
            if result["Status"] in ("Failed", "Cancelled", "TimedOut"):
                raise RuntimeError("Falha ao registrar runner via SSM; consulte status do comando " + command)
            time.sleep(5)
        else:
            raise RuntimeError("Timeout ao registrar runner.")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if any(r["name"] == name and r["status"] == "online"
                   for r in github("/actions/runners?per_page=100")["runners"]):
                print("Runner privado registrado e online.")
                return
            time.sleep(5)
        raise RuntimeError("Runner instalado, mas nao ficou online no GitHub.")
    finally:
        ssm.delete_parameter(Name=parameter)


if __name__ == "__main__":
    main()
