"""Grant each enabled deploy group access to its own SecretProviderClass."""
import json
from pathlib import Path
from registry import load_registry

ROOT = Path(__file__).resolve().parents[1]


def resources(registry):
    items = []
    for name, service in registry.items():
        if not service["enabled"]:
            continue
        metadata = {"name": "kairos-secret-provider-deploy", "namespace": service["namespace"]}
        items.extend([
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": metadata,
                "rules": [{
                    "apiGroups": ["secrets-store.csi.x-k8s.io"],
                    "resources": ["secretproviderclasses"],
                    "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"],
                }],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": metadata,
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": metadata["name"],
                },
                "subjects": [{
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Group",
                    "name": f"kairos:{name}:deploy",
                }],
            },
        ])
    return {"apiVersion": "v1", "kind": "List", "items": items}


if __name__ == "__main__":
    registry = load_registry()
    print(json.dumps(resources(registry), indent=2))
