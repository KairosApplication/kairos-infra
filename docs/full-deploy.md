# Fluxo completo com um unico botao

Workflow: **Complete EKS deployment** em Actions do kairos-infra. Executar na main.

## O que ele executa

1. Confere configuracao, conta AWS, certificado ACM e credenciais do PostgreSQL.
2. Cria/configura bucket de estado privado, criptografado, versionado e com TLS.
3. Cria ou atualiza roles de plan/apply/plataforma e reutiliza o provider OIDC.
4. Planeja Terraform e aplica exatamente o plano salvo, bloqueando exclusoes/substituicoes.
5. Cria EKS, rede privada, ECR, Secrets Manager, maquina do runner e Redis gerenciado.
6. Preenche segredos runtime via SDK; valores nao entram em tfvars, outputs ou logs.
7. Registra o runner dedicado via SSM e espera ficar online.
8. Prepara namespaces, RBAC, IngressClass e CSI Secrets Manager.
9. Testa e publica mobile-api e redis-api e faz rollout por digest.
10. Testa acesso privado autenticado a API Redis e a conexao com Redis.
11. Mostra um resumo unico de todas as etapas, falhando se alguma nao completar.

O fluxo completo ignora as flags dos workflows avancados, pois o clique manual
na main solicita explicitamente todas as etapas. Nao ativar as flags antigas
para tentar corrigir configuracao incompleta.

## Configuracao inicial no GitHub

Tudo fica em **KairosApplication/kairos-infra**.

### Variables

| Nome | Valor |
| --- | --- |
| AWS_ACCOUNT_ID | Conta AWS com 12 digitos. |
| AWS_REGION | Regiao do EKS, Redis, bucket e certificado. |
| TF_STATE_BUCKET | Nome globalmente exclusivo, sem pontos. O workflow cria se ausente. |
| INFRA_CONFIG_JSON | JSON abaixo. |
| DEPLOY_CONFIG_JSON | Host/certificado da API publica, JSON abaixo. |
| RUNNER_APP_ID | ID do GitHub App que registra o runner. |
| AWS_BOOTSTRAP_ROLE_ARN | Role inicial, obrigatoria para OIDC; opcional com chaves IAM. |
| AWS_STATIC_PRINCIPAL_ARN | Com chaves + bootstrap role: ARN do usuario/role dono das chaves. |

INFRA_CONFIG_JSON minimo:

```json
{
  "cluster_name": "kairos-production",
  "cluster_public_access_cidrs": ["SEU-IP-PUBLICO/32"]
}
```

O fluxo acrescenta administrador da plataforma, roles das APIs, runner, AMI AL2023,
provider OIDC e Redis. Administradores adicionais e outras opcoes de rede continuam
aceitos. Para fixar AMI, adicionar deployment_runner_ami_id. Atualizacoes de AMI
que exigem recriar instancia sao bloqueadas pelo guard de exclusoes; manutencao
da maquina exige plano especifico. Nao usar este workflow para rotacionar senha Redis.

DEPLOY_CONFIG_JSON minimo:

```json
{
  "mobile-api": {
    "api_host": "api.seu-dominio.com",
    "certificate_arn": "arn:aws:acm:REGIAO:CONTA:certificate/ID"
  }
}
```

O workflow deriva ARNs das roles das duas APIs sem precisar copiar outputs
manualmente. No fluxo avancado Deploy connected services, usar o mapa completo
com mobile-api e redis-api e os respectivos ARNs, conforme docs/automation.md.

### Secrets

| Nome | Conteudo |
| --- | --- |
| AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY | Par IAM, se usar chaves. Nao e senha de login. OIDC dispensa ambos. |
| AWS_SESSION_TOKEN | Somente para credenciais AWS temporarias. |
| RUNNER_APP_PRIVATE_KEY | PEM da chave privada do App de registro do runner. |
| RUNTIME_SECRETS_JSON | JSON com DB_URL, DB_USERNAME e DB_PASSWORD do PostgreSQL existente. |
| DEPLOY_APP_PRIVATE_KEY | Somente se as APIs forem privadas, em conjunto com DEPLOY_APP_ID. |

Exemplo do formato do Secret RUNTIME_SECRETS_JSON (substituir fora do Git):

```json
{
  "DB_URL": "jdbc:postgresql://HOST:5432/BANCO?sslmode=require",
  "DB_USERNAME": "USUARIO",
  "DB_PASSWORD": "SENHA"
}
```

Ele pode conter outras configuracoes sensiveis da API, como AUTH_SIGNING_KEY.
Sem RUNTIME_SECRETS_JSON, o bootstrap aceita credenciais ja preenchidas no
Secrets Manager. Em execucoes seguintes, campos existentes sao preservados;
valores fornecidos explicitamente no GitHub substituem os mesmos campos.
Chaves internas e senha Redis sao geradas uma vez e preservadas no Secrets Manager.
Uma nova versao do segredo runtime altera a anotacao do pod e provoca rollout.

### GitHub App e Environments

Criar um GitHub App instalado **somente no kairos-infra**, com permissao de
repositorio **Administration: Read and write**, para registrar o runner.
Esse App e distinto do App opcional **Contents: Read-only** que baixa APIs privadas.
O GITHUB_TOKEN comum nao pode registrar runners. A chave de registro passa por
SSM SecureString temporario, nunca por user_data, Terraform ou historico de comandos.

Criar infrastructure-plan, infrastructure-production e production, restritos a main.
Para habilitar planos AWS em PRs no workflow avancado, permitir PRs confiaveis
em infrastructure-plan e exigir revisao antes de liberar credenciais.
Aprovacoes de ambientes, quando configuradas, pausam a Action ate um revisor liberar.

## Configuracao inicial na AWS

Uma identidade IAM inicial precisa existir antes da primeira execucao.
A Action nao consegue criar sua propria primeira credencial.

Usar policy de exemplo em examples/bootstrap-policy.json, substituindo conta,
regiao, bucket e prefixo do cluster. Ela autoriza criar roles limitadas ao prefixo
do projeto, estado, segredos runtime e registro SSM. A role de apply criada pelo
bootstrap possui permissoes amplas de EC2/EKS/ECR/CloudWatch/ElastiCache necessarias
ao provisionamento; o acesso IAM fica no prefixo do cluster. Proteger a main,
os Environments e os mantenedores do infra.

OIDC: a role inicial e o provider precisam ser preparados uma vez pelo administrador,
com audience sts.amazonaws.com e subject
repo:KairosApplication/kairos-infra:environment:infrastructure-production.
Com chaves IAM, cadastrar o par nos Secrets; permissoes sts:AssumeRole precisam
incluir as roles do projeto. Nao usar usuario root.

PostgreSQL precisa estar criado, com schema/migracoes compativeis e acessivel
das subnets privadas. Este fluxo nao cria nem migra o banco externo.

Certificado ACM validado e dominio sao entradas iniciais. Depois do primeiro deploy,
apontar o DNS para o hostname do Ingress/ALB (ou gerencia-lo pelo provedor DNS).
O workflow nao administra sua zona DNS nem cria certificados.

## Redis e segunda API

- redis-api: KairosApplication/kairos-data, subdiretorio redis/, FastAPI/Python 3.12.
- Testes pytest antes de publicar; Dockerfile fallback neste repo.
- Servico interno http://redis-api.kairos-redis-api.svc.cluster.local.
- NetworkPolicy permite apenas pods com label kairos.io/consumer=mobile-api
  no namespace kairos-mobile-api. Nao ha Ingress publico para redis-api.
- Chave KAIROS_INTERNAL_API_KEY compartilhada somente entre as duas APIs.
- Redis 7.1 gerenciado, TLS, autenticacao, criptografia em repouso, duas AZs,
  replica, failover e snapshots. A senha usa auth_token_wo + variavel Terraform
  ephemeral: nao e salva no plano nem no estado.
- Sessoes da API principal e cache de reposicoes usam o endpoint gerenciado.
  As chaves do cache possuem prefixos separados; PostgreSQL continua fonte oficial.

A integracao de negocio na API principal ainda precisa estar na main de
kairos-springboot. As alteracoes locais em feat/kairos-data-restocking-integration
nao sao publicadas automaticamente. As variaveis KAIROS_REDIS_API_ENABLED,
KAIROS_REDIS_API_URL e KAIROS_INTERNAL_API_KEY ja estao preparadas.
O teste final verifica rede/autenticacao/Redis; nao afirma que o endpoint de
negocio da API principal ja publicou e consumiu uma reposicao.

A API principal fica com **uma replica** enquanto o inicializador PostgreSQL da
main ainda nao tem o ajuste de concorrencia da PR #31 fechada. O rollout continua
maxUnavailable=0/maxSurge=1, mas uma replica oferece menor tolerancia a falhas.
A API Redis tem duas replicas. Para ampliar a principal, integrar primeiro o
ajuste de inicializacao e validar migracoes concorrentes.

## Execucao e repeticao

Depois do merge/configuracao: Actions > Complete EKS deployment > Run workflow > main.
A Action nao provisiona nada apenas por abrir esta PR.

Em repeticoes, bucket/roles/segredos/runner sao reutilizados. Terraform gerencia
apenas recursos presentes no seu estado; recursos AWS preexistentes precisam de
importacao, nunca sao adotados por nome automaticamente. Aplicacao e serializada,
ha lock S3, plano salvo e bloqueio de exclusoes. Helm reverte o release em falha;
nao reverte banco, recursos Terraform ja criados nem a outra API.

O runner e persistente, privado, sem SSH/IP publico. Nao rodar PRs nao confiaveis
nele. O codigo da API e testado/compilado em runners GitHub hospedados.
Fora do fluxo completo, o administrador pode manter os workflows avancados,
desde que configure suas variables/flags separadamente.

Custos: EKS, nos, NAT, ALB, Redis replicado, runner EC2, armazenamento e segredos
sao cobrados. Valores reais dependem de regiao e uso.

## Referencias

- [Registro de runners](https://docs.github.com/en/rest/actions/self-hosted-runners)
- [Segredos no SSM Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/running-commands.html)
- [Redis write-only no provider AWS](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/elasticache_replication_group)
