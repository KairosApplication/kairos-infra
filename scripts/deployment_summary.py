"""Fail the orchestrator when any required stage fails, is cancelled or is skipped."""
import json
import os

STAGES = {
    "configuration": "Configuracao",
    "repository-validation": "Validacao do repositorio",
    "infrastructure-validation": "Terraform, Helm e API Redis",
    "secret-scan": "Busca por segredos",
    "deploy": "Infraestrutura, deploy das APIs e verificacao final",
}


def report(results):
    lines = ["## Deploy APIs to EKS", "", "| Etapa | Resultado |", "| --- | --- |"]
    ok = True
    for key, label in STAGES.items():
        result = results.get(key, {}).get("result", "missing")
        if result not in ("success", "failure", "cancelled", "skipped", "missing"):
            result = "unknown"
        lines.append(f"| {label} | {result} |")
        ok = ok and result == "success"
    lines += ["", "Fluxo concluido." if ok else
              "Fluxo nao concluido. Consulte a primeira etapa que nao terminou com success."]
    return "\n".join(lines) + "\n", ok


def main():
    summary, success = report(json.loads(os.environ["DEPLOYMENT_RESULTS"]))
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
        output.write(summary)
    print(summary)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
