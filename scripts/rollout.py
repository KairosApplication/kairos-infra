"""Run atomic Helm while collecting the failing pods BEFORE rollback removes them."""
import argparse
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from diagnostics import kube, summary, error_lines


def collect(namespace, release, stop, path):
    seen = set()
    selector = "app.kubernetes.io/instance=" + release
    with path.open("w", encoding="utf-8") as output:
        while not stop.is_set():
            lines = summary(namespace, selector=selector)
            try:
                pods = json.loads(kube(namespace, "get", "pods", "-l", selector, "-o", "json").stdout)
                for pod in pods["items"]:
                    lines += error_lines(namespace, pod["metadata"]["name"])
            except (subprocess.SubprocessError, ValueError, KeyError):
                pass
            for line in lines:
                if line not in seen:
                    seen.add(line)
                    output.write(line + "\n")
                    output.flush()
            stop.wait(5)


def restore_replicas(namespace, release, replicas):
    current = json.loads(kube(namespace, "get", "deployment", release, "-o", "json").stdout)
    if current["spec"].get("replicas") == 0 and replicas > 0:
        kube(namespace, "scale", "deployment/" + release, "--replicas=" + str(replicas))


def assert_unlocked(namespace, release):
    result = subprocess.run(["helm", "status", release, "-n", namespace, "-o", "json"],
                            capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        if "release: not found" not in result.stderr.lower():
            raise ValueError("Nao foi possivel consultar o estado Helm antes da transicao.")
    elif json.loads(result.stdout)["info"]["status"].startswith("pending-"):
        raise ValueError("Release Helm pendente. Recupere a operacao antes da transicao do pool.")


def deploy(release, namespace, values, overrides, initial_pool_transition=False, expected="kairosdb"):
    replicas = None
    try:
        assert_unlocked(namespace, release)
        if initial_pool_transition:
            if release != "mobile-api":
                raise ValueError("Transicao de pool permitida apenas para mobile-api.")
            current = kube(namespace, "get", "deployment", release, "--ignore-not-found=true", "-o", "json")
            if current.stdout.strip():
                replicas = json.loads(current.stdout)["spec"].get("replicas", 1)
                kube(namespace, "scale", "deployment/" + release, "--replicas=0")
                selector = "app.kubernetes.io/instance=" + release
                for attempt in range(30):
                    pods = json.loads(kube(namespace, "get", "pods", "-l", selector, "-o", "json").stdout)
                    if not pods["items"]:
                        break
                    time.sleep(5)
                else:
                    raise ValueError("Pods antigos nao encerraram; transicao de pool interrompida.")
        if release == "mobile-api":
            from preflight_database import run as preflight
            preflight(namespace, expected, values, overrides)
        run(release, namespace, values, overrides)
    finally:
        if replicas is not None:
            # Restore the live app if the preflight/upgrade failed after scaling
            # down. Do not override a successful Helm replica configuration.
            restore_replicas(namespace, release, replicas)


def run(release, namespace, values, overrides, command=subprocess.run):
    path = Path(os.environ["RUNNER_TEMP"]) / (release + "-diagnostics.log")
    stop = threading.Event()
    collector = threading.Thread(target=collect, args=(namespace, release, stop, path), daemon=True)
    collector.start()
    try:
        result = command(["helm", "upgrade", "--install", release, "charts/kairos-api",
                          "--namespace", namespace, "-f", values, "-f", overrides,
                          "--atomic", "--wait", "--timeout", "15m", "--history-max", "10"], check=False)
    finally:
        stop.set()
        collector.join(timeout=90)
    if result.returncode:
        if path.exists():
            print(path.read_text(encoding="utf-8")[-20000:])
        raise SystemExit(result.returncode)
    command(["kubectl", "rollout", "status", "deployment/" + release,
             "--namespace", namespace, "--timeout=60s"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for option in ("release", "namespace", "values", "overrides"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--expected-database", default="kairosdb")
    parser.add_argument("--initial-pool-transition", action="store_true")
    args = parser.parse_args()
    deploy(args.release, args.namespace, args.values, args.overrides,
           args.initial_pool_transition, args.expected_database)
