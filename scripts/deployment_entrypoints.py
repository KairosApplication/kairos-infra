"""Validate public and private API entrypoints without accessing AWS."""
import re


def validate_entrypoint(service, values, account, region):
    mode = values.setdefault("entrypoint", "custom-domain" if service == "mobile-api" else "private")
    if mode not in ("private", "custom-domain", "cloudfront"):
        raise ValueError("entrypoint deve ser private, custom-domain ou cloudfront.")
    host, certificate = values.get("api_host"), values.get("certificate_arn")
    if service == "mobile-api" and mode == "private":
        raise ValueError("A API principal exige um endpoint publico.")
    if service not in ("mobile-api", "agent-api") and mode != "private":
        raise ValueError("O servico Redis deve permanecer privado.")
    if mode in ("private", "cloudfront"):
        if host or certificate:
            raise ValueError("Nao configurar dominio/certificado proprio nesse modo.")
        return mode
    if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", host):
        raise ValueError("Configure api_host valido para o dominio proprio.")
    if not isinstance(certificate, str) or not certificate.startswith(f"arn:aws:acm:{region}:{account}:certificate/"):
        raise ValueError("Configure certificado ACM da mesma conta/regiao do ALB.")
    return mode
