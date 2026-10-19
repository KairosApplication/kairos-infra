"""Check live service-to-service access and Redis authentication after both releases."""
import json
import subprocess
import urllib.request


def main():
    # Read the key inside an existing mobile pod, never in CI output or process arguments.
    program = """import urllib.request,json
base=__import__('os').environ['KAIROS_REDIS_API_URL']
key=__import__('os').environ['KAIROS_INTERNAL_API_KEY']
r=urllib.request.urlopen(base+'/health',timeout=10)
assert r.status==200
req=urllib.request.Request(base+'/v1/restockings/week?company_id=2147483647&employee_id=2147483647',
    headers={'X-Internal-API-Key':key})
with urllib.request.urlopen(req,timeout=10) as r:
    assert r.status==200
print('Redis API autenticada e conectada ao Redis.')
"""
    # Mobile image has Java, not Python. Use a short-lived probe in its namespace
    # with the same pod label and internal key mounted from the existing runtime Secret.
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {
        "name": "kairos-integration-probe", "namespace": "kairos-mobile-api",
        "labels": {"kairos.io/consumer": "mobile-api"}},
        "spec": {"restartPolicy": "Never", "automountServiceAccountToken": False,
          "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                             "seccompProfile": {"type": "RuntimeDefault"}},
          "containers": [{"name": "probe", "image": "python:3.12-slim",
            "command": ["python", "-c", program],
            "env": [{"name": "KAIROS_REDIS_API_URL",
                     "value": "http://redis-api.kairos-redis-api.svc.cluster.local"},
                    {"name": "KAIROS_INTERNAL_API_KEY", "valueFrom": {"secretKeyRef": {
                      "name": "mobile-api-env", "key": "KAIROS_INTERNAL_API_KEY"}}}],
            "resources": {"requests": {"cpu": "50m", "memory": "64Mi"},
                          "limits": {"cpu": "250m", "memory": "128Mi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]}}}]}}
    subprocess.run(["kubectl", "delete", "pod", "kairos-integration-probe",
                    "-n", "kairos-mobile-api", "--ignore-not-found=true", "--wait=true"], check=True)
    try:
        subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(pod), text=True, check=True)
        subprocess.run(["kubectl", "wait", "--for=jsonpath={.status.phase}=Succeeded",
                        "pod/kairos-integration-probe", "-n", "kairos-mobile-api", "--timeout=180s"], check=True)
        print("Conectividade privada, autenticacao interna e Redis verificados.")
    finally:
        subprocess.run(["kubectl", "delete", "pod", "kairos-integration-probe",
                        "-n", "kairos-mobile-api", "--ignore-not-found=true"], check=False)


if __name__ == "__main__":
    main()
