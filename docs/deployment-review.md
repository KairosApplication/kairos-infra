# Revisão do fluxo de deploy — 02/11/2026

Entrada normal: **Deploy APIs to EKS**, na main. O fluxo chama full-deploy,
provision, reconcile e reusable-release no próprio kairos-infra.

## Resultado da revisão

A permissão `ecr:GetLifecyclePolicy` estava ausente no planejamento de recursos
existentes e foi corrigida com escopo em `kairos/*` da conta/região configuradas.
Não foi encontrada outra permissão de leitura ausente no inventário revisado.

Os testes de `tests/test_refresh_permissions.py` confrontam o contrato de leitura
com as policies de plan/apply e exigem que cada tipo de recurso Terraform tenha
uma entrada no inventário. Também verificam as consultas das policies CloudFront
e acesso aos objetos de estado/lock S3. Esses testes não simulam SCP, boundaries,
estado remoto, quotas nem todos os caminhos internos do provider.

## Etapas conferidas

| Etapa | Verificação |
| --- | --- |
| Configuração | main do infra, conta/região, CIDRs, JSON, par de chaves ou role OIDC. |
| Bootstrap | Identidade imutável GitHub, bucket privado/versionado, roles, senha Redis preservada, AMI existente reutilizada. |
| Plan/apply | Refresh de recursos existentes, estado S3/lock, plano salvo, autenticação separada, rejeição de exclusões/substituições. |
| Runner | AWS CLI AL2023, pip/unzip, usuário idempotente, recuperação de cloud-init, token via SSM temporário e checksum. |
| Plataforma | IngressClass do Auto Mode, controller de NetworkPolicy, chart AWS CSI/Pod Identity, CRD e RBAC. |
| Releases | Cadastro dos três serviços, main/SHA, Java 21, perfil PostgreSQL só na principal, Python 3.12 na Redis API, ECR por digest. |
| Pods | Portas 8080/8081/8001, /health, nomes de segredos, service account/Pod Identity, rede interna e chave da Redis API. |
| CloudFront | ALB privado ativo, conta/ownership, prefix list IPv4, estado separado, cache desabilitado, métodos/cookies/autorização encaminhados. |
| Resultado | Smoke privado Redis, health HTTPS das duas APIs e falha do resumo quando uma etapa obrigatória não termina. |

Os contratos de configuração foram conferidos com application.yaml das APIs
Java e redis/app/main.py da API Redis na main dos repositórios de origem.
Isso não executou chamadas autenticadas de negócio ou migrações.

## Pontos que ainda dependem da execução real

- Rede, credenciais, schema e permissões PostgreSQL/MongoDB. Health/readiness
  não substituem testes de login, autorização, consultas e transações.
- Quotas e capacidade da conta: EC2/vCPU, Auto Mode, ALBs, ENIs/IPs, Redis e
  CloudFront. Redis API exige dois nós distintos; um rollout pode precisar de
  um terceiro. Não aumentar quotas, habilitar flags ou abrir redes automaticamente.
- O PostgreSQL da Aiven tem limite de conexões conforme o plano. Considerar
  conexões de pods antigos e novos durante maxSurge e as conexões de migração.
- A API principal usa `CORS_ALLOWED_ORIGINS`, com padrão localhost:5173. Para a
  web externa, configurar a origem HTTPS real em env dos values da principal e
  validar cookies/CSRF. Não usar wildcard para contornar autenticação. Colocar
  uma chave extra no JSON de runtime não a injeta automaticamente: o chart monta
  apenas as chaves declaradas em secrets.keys.
- A API de IA exige Bearer em /api/v1/** e mantém escritas MongoDB desabilitadas.
- Aprovações de Environments, conectividade privada e runner online continuam
  necessários. SDK, quotas e service-linked roles podem ter restrições da conta
  que os testes locais não veem.

## Como verificar depois do merge

Iniciar uma nova execução de **Deploy APIs to EKS** na main. Re-run de um run
antigo mantém o código antigo. Conferir o primeiro job com erro e o resumo final;
não considerar validação local ou CI como evidência de deploy completo.

## Referências revisadas

- [Provider AWS 6.70: leitura da política ECR](https://github.com/hashicorp/terraform-provider-aws/blob/v6.70.0/internal/service/ecr/lifecycle_policy.go)
- [Provider AWS 6.70: origem VPC](https://github.com/hashicorp/terraform-provider-aws/blob/v6.70.0/internal/service/cloudfront/vpc_origin.go)
- [AWS: requisitos da origem VPC CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)
- [AWS: NetworkPolicy no Auto Mode](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html)
