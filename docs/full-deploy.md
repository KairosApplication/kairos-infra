# Fluxo completo com um unico botao

Ponto de entrada recomendado: [Deploy APIs to EKS](deploy-apis.md), que executa as validacoes e chama
o workflow **Complete EKS deployment** abaixo. Ambos executam somente na main.

## O que ele executa

1. Confere configuracao, conta AWS, credenciais do PostgreSQL e certificado ACM quando usar dominio proprio.
2. Cria/configura bucket de estado privado, criptografado, versionado e com TLS.
3. Cria ou atualiza roles de plan/apply/plataforma e reutiliza o provider OIDC.
4. Planeja Terraform e aplica exatamente o plano salvo, bloqueando exclusoes/substituicoes.
5. Cria EKS, rede privada, ECR, Secrets Manager, maquina do runner e Redis gerenciado.
6. Preenche segredos runtime via SDK; valores nao entram em tfvars, outputs ou logs.
7. Registra o runner dedicado via SSM e espera ficar online.
8. Prepara namespaces, RBAC, IngressClass e CSI Secrets Manager.
9. Testa e publica mobile-api, agent-api e redis-api e faz rollout por digest.
10. Testa acesso privado autenticado a API Redis e a conexao com Redis.
11. No modo cloudfront, cria/atualiza origem VPC e distribuicao HTTPS e testa a URL publica.
12. Mostra um resumo unico de todas as etapas, falhando se alguma nao completar.

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
| DEPLOY_CONFIG_JSON | Modo CloudFront ou host/certificado proprio, JSON abaixo. |
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
aceitos. O bootstrap reutiliza a AMI do runner existente; em instalacao nova resolve a AMI publica.
Para fixar AMI, adicionar deployment_runner_ami_id. Atualizacoes de AMI
que exigem recriar instancia sao bloqueadas pelo guard de exclusoes; manutencao
da maquina exige plano especifico. Nao usar este workflow para rotacionar senha Redis.

DEPLOY_CONFIG_JSON sem dominio proprio (opcao escolhida para Kairos):

```json
{"mobile-api":{"entrypoint":"cloudfront"},"agent-api":{"entrypoint":"cloudfront"}}
```

A URL `https://....cloudfront.net` aparece no resumo da etapa edge apos o deploy.
Nao cadastrar `api_host` nem `certificate_arn` nesse modo. Nao precisa comprar
um dominio, editar DNS ou emitir certificado ACM. O ALB fica privado, recebe
apenas HTTP da prefix list gerenciada CloudFront e nao tem acesso publico direto.
O cliente usa HTTPS; o trecho CloudFront-ALB usa a conexao privada VPC.
Cache desabilitado, cookies, Authorization, query strings e metodos de escrita
sao encaminhados para a API. Nenhum estado autenticado e compartilhado pelo cache.
O Host publico e o protocolo CloudFront-Forwarded-Proto sao encaminhados.
A API Spring/Tomcat usa esses dados para reconhecer HTTPS, sem confiar em
X-Forwarded-Host/Port fornecidos pelo cliente. Validar os fluxos de autenticacao
com as versoes reais das APIs antes de usar em producao.

O modulo `terraform/edge` usa estado separado `production/cloudfront.tfstate`
no mesmo bucket, com lock, plano salvo, guard de exclusoes e prevent_destroy.
O fluxo aguarda a distribuicao ser implantada e testa `/health` por HTTPS.
CloudFront e um recurso adicional cobrado conforme plano/uso da conta AWS.
Nao trocar o modo de um Ingress ja publicado sem planejar a migracao do ALB.
Os workflows avancados de release nao criam a distribuicao: usar o fluxo completo.

DEPLOY_CONFIG_JSON com dominio proprio (opcional):

```json
{
  "mobile-api": {
    "api_host": "api.seu-dominio.com",
    "certificate_arn": "arn:aws:acm:REGIAO:CONTA:certificate/ID"
  }
}
```

O workflow deriva ARNs das roles das APIs habilitadas sem precisar copiar outputs
manualmente. No fluxo avancado Deploy connected services, usar o mapa completo
com mobile-api e redis-api e os respectivos ARNs, conforme docs/automation.md.

### Secrets

| Nome | Conteudo |
| --- | --- |
| AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY | Par IAM, se usar chaves. Nao e senha de login. OIDC dispensa ambos. |
| AWS_SESSION_TOKEN | Somente para credenciais AWS temporarias. |
| RUNNER_APP_PRIVATE_KEY | PEM da chave privada do App de registro do runner. |
| AGENT_RUNTIME_SECRETS_JSON | URI MongoDB direta ou JSON com MONGODB_URI e MONGODB_DATABASE da API de IA. |
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
ao provisionamento; o acesso IAM fica no prefixo do cluster. CloudFront permite criar recursos com tag Project=Kairos
e atualizar distribuicoes/origens dessa conta com essa tag. Proteger a main,
os Environments e os mantenedores do infra.

OIDC: a role inicial e o provider precisam ser preparados uma vez pelo administrador,
com audience sts.amazonaws.com e subject
repo:KairosApplication@293899017/kairos-infra@1400182943:environment:infrastructure-production.
Com chaves IAM, cadastrar o par nos Secrets; permissoes sts:AssumeRole precisam
incluir as roles do projeto. Nao usar usuario root.

PostgreSQL precisa estar criado, com schema/migracoes compativeis e acessivel
das subnets privadas. Este fluxo nao cria nem migra o banco externo.

No modo custom-domain, certificado ACM validado e dominio sao entradas iniciais. Depois do primeiro deploy,
apontar o DNS para o hostname do Ingress/ALB (ou gerencia-lo pelo provedor DNS).
O workflow nao administra sua zona DNS nem cria certificados ACM. No modo cloudfront, usa o dominio e certificado gerenciados pela AWS.

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

Depois do merge/configuracao: Actions > Deploy APIs to EKS > Run workflow > main.
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

### Recuperacao da preparacao do runner

A AMI Amazon Linux 2023 usa o pacote `awscli-2`, nao `awscli2`. O script
`scripts/runner-prerequisites.sh` e compartilhado pelo user_data e pelo registro
SSM, instala tambem pip/unzip e preserva o usuario existente. Se cloud-init
registrou uma falha anterior, o registro avisa e tenta preparar novamente as
dependencias; falhas na instalacao continuam interrompendo o fluxo.
Nao e necessario apagar a instancia ou recriar o cluster para essa recuperacao.
Alterar user_data pode exigir parada/inicio da EC2 conforme o plano Terraform;
isso afeta o runner, nao os pods das APIs. Conferir o plano salvo.

CloudFront usa um virtualenv temporario para boto3, evitando instalar dependencias
no Python da AWS CLI. Cada job de cluster usa um kubeconfig temporario. O fluxo
espera o ALB sair de provisioning antes de criar a origem VPC, sem aceitar ALBs
de outra conta ou cluster.

Depois de integrar uma correcao de codigo na main, iniciar uma nova execucao de
Deploy APIs to EKS. Re-run de uma execucao antiga utiliza o commit antigo.

## Referencias

- [Registro de runners](https://docs.github.com/en/rest/actions/self-hosted-runners)
- [Segredos no SSM Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/running-commands.html)
- [Redis write-only no provider AWS](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/elasticache_replication_group)

## PostgreSQL na Aiven

Usar o endpoint de conexao do servico, com porta real da Aiven (nao presumir 5432)
e `jdbc:postgresql://HOST:PORTA/BANCO?sslmode=require` em DB_URL. Preencher
DB_USERNAME e DB_PASSWORD somente no Secret RUNTIME_SECRETS_JSON do kairos-infra.
A Aiven exige TLS. Para validacao completa da identidade do servidor, configurar
a CA do projeto e sslmode=verify-full na aplicacao; sslmode=require criptografa,
mas nao verifica a identidade do servidor.

Conferir no console da Aiven se o servico esta ativo, possui endpoint publico e
se ha IP address allowlist. As APIs saem das subnets privadas pelo NAT da AWS.
Se houver allowlist, liberar os IPs publicos /32 do NAT, nao os IPs dos pods nem
os IPs do GitHub Actions. Sem essa liberacao, nao presumir conectividade.
Credenciais corretas, acesso de rede e schema compativel continuam necessarios;
os testes locais de infraestrutura nao provam acesso ao banco real.

## API de IA

agent-api agora usa KairosApplication/kairos-api-ia. Consulte [agent-api.md](agent-api.md)
para MongoDB, token Bearer, URL CloudFront e comportamento de escrita. A API Redis
continua sendo uma dependencia interna separada.
