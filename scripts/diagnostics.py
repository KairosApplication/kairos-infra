"""Bounded Kubernetes diagnostics without dumping manifests, env or Secret values."""
import json
import re
import subprocess


def kube(namespace, *args, check=True):
    return subprocess.run(["kubectl", "--request-timeout=10s", "-n", namespace, *args],
                          capture_output=True, text=True, timeout=15, check=check)


def summary(namespace, selector=None, pod_name=None):
    """Allowlist status fields; never run describe, get Secret, or dump pod specs."""
    try:
        args = ["get", "pods", "-o", "json"]
        args += [pod_name] if pod_name else ["-l", selector]
        result = kube(namespace, *args)
        data = json.loads(result.stdout)
        pods = [data] if pod_name else data["items"]
        lines = []
        for pod in pods:
            status = pod.get("status", {})
            containers = [{"name": c["name"], "ready": c.get("ready"),
                           "restarts": c.get("restartCount"),
                           "state": {kind: {key: value for key, value in detail.items()
                                             if key in ("reason", "exitCode", "signal")}
                                     for kind, detail in c.get("state", {}).items()},
                           "last_state": {kind: {key: value for key, value in detail.items()
                                                  if key in ("reason", "exitCode", "signal")}
                                          for kind, detail in c.get("lastState", {}).items()}}
                          for c in status.get("containerStatuses", [])]
            lines.append(json.dumps({"pod": pod["metadata"]["name"],
                                     "phase": status.get("phase"), "containers": containers}))
        events = kube(namespace, "get", "events", "-o", "json")
        names = {p["metadata"]["name"] for p in pods}
        for event in json.loads(events.stdout)["items"][-40:]:
            obj = event.get("involvedObject", {})
            if obj.get("name") in names:
                lines.append(json.dumps({"reason": event.get("reason"), "type": event.get("type"),
                                         "count": event.get("count"), "object": obj.get("name"),
                                         "signatures": [s for s in ("Insufficient cpu", "Insufficient memory",
                                             "connection refused", "timed out", "AccessDenied", "not authorized")
                                             if s in event.get("message", "")]}))
        return lines
    except (subprocess.SubprocessError, ValueError, KeyError):
        return ["Diagnostico Kubernetes indisponivel; consulte o namespace indicado."]


def error_lines(namespace, pod):
    """Keep error signatures, not arbitrary app output which may contain business data."""
    lines = []
    for previous in ([], ["--previous"]):
        try:
            result = kube(namespace, "logs", pod, "--tail=100", "--limit-bytes=32768", *previous, check=False)
            for line in result.stdout.splitlines():
                # App messages can include credentials or customer data. Only emit
                # exception class names and a fixed vocabulary of useful signatures.
                match = re.search(r"Caused by: ([A-Za-z0-9_.$]+(?:Exception|Error))", line)
                match = match or re.search(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):", line)
                if match:
                    lines.append("Exception class: " + match.group(1))
                for signature in ("remaining connection slots are reserved", "Connection is not available",
                                  "password authentication failed", "Connection refused",
                                  "Schema-validation", "Failed to obtain JDBC Connection",
                                  "OutOfMemoryError", "Could not resolve placeholder",
                                  "HTTP Error 401", "HTTP Error 403", "HTTP Error 503",
                                  "Temporary failure in name resolution", "Illegal base64 character"):
                    if signature in line:
                        lines.append("Application error: " + signature)
        except subprocess.SubprocessError:
            pass
    return lines[-16:]
