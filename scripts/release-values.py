"""Write deployment overrides without reading credentials."""
import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-repository", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--host", default="")
    parser.add_argument("--certificate-arn", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.digest):
        parser.error("Digest de imagem invalido.")
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_sha):
        parser.error("SHA do codigo invalido.")
    if not re.fullmatch(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/kairos/(mobile-api|agent-api)", args.image_repository):
        parser.error("Repositorio ECR invalido.")
    overrides = {
        "image": {"repository": args.image_repository, "digest": args.digest},
        "sourceRevision": args.source_sha,
        "aws": {"region": args.region},
    }
    if args.host:
        if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", args.host):
            parser.error("Host invalido: use somente o dominio, sem https:// ou caminho.")
        if not re.fullmatch(r"arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-f0-9-]+", args.certificate_arn):
            parser.error("Informe o ARN ACM do certificado HTTPS validado.")
        overrides["ingress"] = {"host": args.host, "certificateArn": args.certificate_arn}
    elif args.certificate_arn:
        parser.error("Informe o dominio junto do certificado.")
    Path(args.output).write_text(json.dumps(overrides, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
