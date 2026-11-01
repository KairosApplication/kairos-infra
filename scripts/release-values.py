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
    parser.add_argument("--entrypoint", choices=["private", "custom-domain", "cloudfront"], default="custom-domain")
    parser.add_argument("--cloudfront-prefix-list-id", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.digest):
        parser.error("Digest de imagem invalido.")
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_sha):
        parser.error("SHA do codigo invalido.")
    if not re.fullmatch(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/kairos/[a-z][a-z0-9-]{0,38}[a-z0-9]", args.image_repository):
        parser.error("Repositorio ECR invalido.")
    overrides = {
        "image": {"repository": args.image_repository, "digest": args.digest},
        "sourceRevision": args.source_sha,
        "aws": {"region": args.region},
    }
    if args.entrypoint == "cloudfront":
        if args.host or args.certificate_arn or not re.fullmatch(r"pl-[a-f0-9]+", args.cloudfront_prefix_list_id):
            parser.error("CloudFront exige prefix list e nao recebe dominio/certificado proprio.")
        overrides["ingress"] = {"enabled": True, "entrypoint": "cloudfront", "className": "kairos-cloudfront",
                                "host": "", "certificateArn": "",
                                "cloudfrontPrefixListId": args.cloudfront_prefix_list_id}
        overrides["networkPolicy"] = {"enabled": False}
        # Preserve the viewer's HTTPS scheme. The ALB receives private HTTP;
        # trust the CloudFront-generated protocol header, not viewer-supplied forwarded metadata.
        overrides["env"] = {"SERVER_FORWARD_HEADERS_STRATEGY": "native",
                            "SERVER_TOMCAT_REMOTEIP_PROTOCOL_HEADER": "CloudFront-Forwarded-Proto",
                            "SERVER_TOMCAT_REMOTEIP_HOST_HEADER": "",
                            "SERVER_TOMCAT_REMOTEIP_PORT_HEADER": "",
                            "SERVER_TOMCAT_REDIRECT_CONTEXT_ROOT": "false"}
    elif args.entrypoint == "private":
        if args.host or args.certificate_arn:
            parser.error("API privada nao usa dominio/certificado.")
        overrides["ingress"] = {"enabled": False}
    elif args.host:
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
