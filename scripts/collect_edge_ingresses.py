"""Read only the Ingress resources of registered CloudFront API releases."""
import json
import os
import subprocess
from pathlib import Path
from registry import load_registry


def main():
    registry = load_registry()
    services = json.loads(os.environ["CLOUDFRONT_SERVICES"])
    result = {}
    for name in services:
        if name not in registry or not registry[name]["enabled"] or name not in ("mobile-api", "agent-api"):
            raise ValueError("Servico CloudFront nao autorizado.")
        item = registry[name]
        target = "ingress/" + item["release"]
        namespace = item["namespace"]
        subprocess.run(["kubectl", "wait", "--for=jsonpath={.status.loadBalancer.ingress[0].hostname}",
                        target, "-n", namespace, "--timeout=10m"], check=True)
        result[name] = json.loads(subprocess.check_output(["kubectl", "get", target, "-n", namespace, "-o", "json"]))
    Path(os.environ["RUNNER_TEMP"], "api-ingresses.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
