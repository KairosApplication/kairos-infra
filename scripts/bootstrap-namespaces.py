"""Create namespaces only for explicitly enabled services."""
import json
from registry import load_registry


def resources(registry):
    return {'apiVersion': 'v1', 'kind': 'List', 'items': [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
            'name': service['namespace'], 'labels': {
                'pod-security.kubernetes.io/enforce': 'restricted',
                'pod-security.kubernetes.io/enforce-version': 'latest',
                'pod-security.kubernetes.io/audit': 'restricted',
                'pod-security.kubernetes.io/warn': 'restricted'}}}
        for service in registry.values() if service['enabled']]}


if __name__ == '__main__':
    print(json.dumps(resources(load_registry())))
