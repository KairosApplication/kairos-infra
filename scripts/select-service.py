"""Resolve a trusted caller to its infrastructure service."""
import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def select(service, repository, source_sha):
    registry = json.loads((ROOT / "services.json").read_text(encoding="utf-8"))
    if service not in registry:
        raise ValueError("Servico desconhecido.")
    item = registry[service]
    if not item["enabled"]:
        raise ValueError("A API do agente ainda esta desabilitada.")
    if repository != item["source_repository"]:
        raise ValueError("O repositorio chamador nao corresponde a esta API.")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Informe o SHA completo do commit da API.")
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    item = select(args.service, args.repository, args.source_sha)
    outputs = {
        "namespace": item["namespace"],
        "release": item["release"],
        "ecr_repository": item["ecr_repository"],
        "values": item["values"],
        "fallback_dockerfile": item["fallback_dockerfile"] or "",
        "source_sha": args.source_sha,
    }
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as stream:
            for key, value in outputs.items():
                stream.write(f"{key}={value}\n")
    print(json.dumps(outputs))


if __name__ == "__main__":
    main()
