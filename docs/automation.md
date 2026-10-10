# Automacao AWS e deploy das APIs

## Fluxos implementados

| Workflow | Trigger | Resultado |
| --- | --- | --- |
| `validate.yml` e `secret-scan.yml` | PR, push em main ou manual | Validacao local, testes simulados e busca por segredos, sem provisionar AWS. |
| `provision.yml` | PR, push em main ou manual | Plano AWS com estado S3; somente main pode aplicar o plano salvo. |
| `reconcile.yml` | Manual, a cada 30 minutos ou depois de provisionar em main | Resolve os commits de main e executa build e deploy de cada API habilitada no proprio infra. |
| `reusable-release.yml` | Chamada local pelo reconcile | Testes, imagem ECR, classificacao do release e rollout EKS. |

Todo o fluxo executa no Actions do `kairos-infra`. Nao instalar workflow de deploy,
Secrets AWS, environments ou runners nos repositorios das APIs ou no repo .github.
O codigo da API e obtido por checkout do SHA atual da main cadastrado na matriz.
Antes de implantar, o pipeline verifica novamente se esse SHA continua atual.

O agendamento consulta as APIs a cada 30 minutos; o GitHub pode atrasar execucoes.
Push em outro repositorio nao dispara diretamente o workflow do infra.
Para executar imediatamente, usar Actions > Deploy connected services > Run workflow.
O primeiro build de cada commit Java executa verify com PostgreSQL. Se a imagem
imutavel desse SHA ja existe, ela e reutilizada sem repetir os testes/build.
Mesmo sem mudancas, Helm reconcilia o release para corrigir drift sem reiniciar pods
quando o manifesto e igual. Somente o pipeline deve ter permissao de publicar no ECR.

## Cadastro unico de servicos

`services.json` e a lista explicita de repositorios conectados. Somente entradas
com `enabled: true` participam do Terraform, bootstrap Kubernetes e reconciliacao.
Nao ocorre descoberta nem publicacao de todos os repositorios da organizacao.

Para cadastrar outra API:

1. Criar seus values em `environments/production`, configurar porta, health, segredos e acesso.
2. Adicionar entrada exclusiva no cadastro com repositorio real, namespace, release,
   ECR `kairos/NOME`, arquivo de values e `build_kind` (`java21` ou `docker`).
3. Para `java21`, a API deve implementar o perfil Maven `postgres-tests`; para `docker`,
   fornecer Dockerfile e CI no repositorio. Adaptar testes do pipeline conforme a stack.
4. Configurar o servico em DEPLOY_CONFIG_JSON do infra. Habilitar somente depois
   que os testes e os endpoints estiverem prontos.
5. Integrar o cadastro, revisar o plano e aplicar para criar ECR, roles, acesso e segredo.
6. Executar o bootstrap da plataforma para gerar seu namespace e RBAC.

O pipeline gera `services` do Terraform diretamente do cadastro. Nao colocar
`services` em `INFRA_CONFIG_JSON`. Execucoes locais podem gerar o mesmo arquivo:

```sh
python scripts/registry.py > /tmp/kairos-services.json
# O JSON gerado e o mapa services; coloca-lo dentro de {"services": ...}
# em um arquivo .tfvars.json para usar com -var-file.
```

A API do agente permanece desabilitada. O cadastro nao decide automaticamente
se uma API nova ja esta pronta.

## Configuracao no GitHub

Integrar a PR do infra. O workflow da organizacao e o chamador na API foram removidos.
Antes de ativar duas replicas, integrar o ajuste de concorrencia PostgreSQL da API.

No `kairos-infra`, criar estas repository variables:

| Variable | Valor |
| --- | --- |
| `AWS_ACCOUNT_ID`, `AWS_REGION` | Conta e regiao reais. |
| `TF_STATE_BUCKET` | Bucket privado criado por `terraform/bootstrap`. |
| `INFRA_CONFIG_JSON` | JSON de configuracao abaixo, sem senhas. |
| `AWS_INFRA_PLAN_ROLE_ARN` | Role de leitura de metadados AWS e acesso ao estado/lock S3. |
| `AWS_INFRA_APPLY_ROLE_ARN` | Role de provisionamento autorizada a gerenciar os recursos deste Terraform. |
| `AWS_PLATFORM_ROLE_ARN` | Role administradora do cluster, listada em `cluster_admin_principal_arns`. |
| `KAIROS_INFRA_ENABLED` | `true` depois de preparar bucket, roles e ambientes. |
| `KAIROS_PLATFORM_ENABLED` | `true` depois de registrar o runner com acesso ao EKS. |
| `KAIROS_RECONCILE_ENABLED` | `true` depois de conectar APIs e instalar o GitHub App. |
| `DEPLOY_APP_ID` | Opcional: App com Contents read para APIs privadas. |
| `EKS_CLUSTER_NAME` | Nome real do cluster provisionado. |
| `DEPLOY_CONFIG_JSON` | Mapa por servico com roles e dominio/certificado; exemplo abaixo. |

Exemplo de `INFRA_CONFIG_JSON`; substituir os valores de exemplo:

```json
{
  "cluster_name": "kairos-production",
  "kubernetes_version": "1.35",
  "cluster_public_access_cidrs": ["203.0.113.10/32"],
  "cluster_admin_principal_arns": ["arn:aws:iam::123456789012:role/KairosPlatformAdmin"],
  "single_nat_gateway": true,
  "github_oidc_provider_arn": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
}
```

Criar os Environments `infrastructure-plan`, `infrastructure-production` e
`production`. Exigir revisao em `infrastructure-plan` antes de
executar codigo de uma PR com acesso AWS; somente PRs do proprio repositorio
podem solicitar esse plano. Em `infrastructure-production` e `production`,
restringir branches a main e configurar revisao antes do apply se desejado.
As verificacoes sem AWS continuam rodando enquanto a automacao estiver desabilitada.

As roles de plan/apply sao preparadas uma vez por um administrador, fora do pipeline
que depende delas. Para OIDC, confiar no provider GitHub, audience `sts.amazonaws.com`
e subjects exatos `repo:KairosApplication/kairos-infra:environment:infrastructure-plan`
ou `...:environment:infrastructure-production`, conforme o job. A role de plataforma
tambem usa o Environment infrastructure-production e precisa de acesso administrativo EKS.
Plan precisa das leituras de EC2/VPC, EKS, IAM, ECR, Secrets Manager (apenas metadados),
CloudWatch e do estado S3; os dois jobs precisam de acesso ao objeto de estado e lock.
Nao conceder leitura de valores de segredos ao planejador.

### Chaves AWS em Secrets (opcional)

OIDC dispensa chaves permanentes. Se optar por chaves, criar `AWS_ACCESS_KEY_ID`
e `AWS_SECRET_ACCESS_KEY` somente nos Secrets do `kairos-infra`. Para credenciais temporarias, incluir tambem
`AWS_SESSION_TOKEN` e atualizar antes de expirarem. O workflow central encaminha esses Secrets ao release local.

O pipeline usa essas chaves para assumir as roles configuradas. Para infra,
as roles de plan/apply/plataforma precisam confiar explicitamente no principal IAM
das chaves. Para a API, adicionar ao JSON de infra:

```json
"github_static_principal_arns": {
  "mobile-api": "arn:aws:iam::123456789012:user/KairosMobileDeploy"
}
```

O principal precisa de `sts:AssumeRole` para as roles publisher/deployer dessa API.
Ele nao recebe acesso ao EKS apenas por ter chaves AWS. Esse principal nao deve
ter permissoes administrativas; as roles de aplicacao permanecem limitadas a ECR,
metadados do proprio segredo e namespace. Sem esses Secrets, a action usa OIDC.
Nao colocar chaves em Variables, tfvars, user_data ou no cadastro de servicos.

### Configuracao de deploy e acesso ao codigo

Criar DEPLOY_CONFIG_JSON como Variable do kairos-infra, usando os ARNs do output
Terraform services, o dominio e o certificado ACM validados:

```json
{
  "mobile-api": {
    "publisher_role_arn": "arn:aws:iam::123456789012:role/kairos-production-mobile-api-publish",
    "deployer_role_arn": "arn:aws:iam::123456789012:role/kairos-production-mobile-api-deploy",
    "api_host": "api.seu-dominio.com",
    "certificate_arn": "arn:aws:acm:us-east-1:123456789012:certificate/ID-REAL"
  }
}
```

Configurar exatamente as entradas enabled:true do services.json, sem senhas.
As roles OIDC das APIs agora confiam na main do kairos-infra para publicar e no
Environment production do kairos-infra para implantar. Aplicar esse Terraform
antes de executar o release; roles antigas que confiam no repo da API devem ser atualizadas.

Para APIs publicas, o GITHUB_TOKEN do infra acessa o codigo publico, sem App.
Para APIs privadas, criar um GitHub App com **Contents: Read-only**, instala-lo
somente nas APIs cadastradas, configurar DEPLOY_APP_ID e guardar a chave em
DEPLOY_APP_PRIVATE_KEY no infra. Os tokens temporarios sao gerados por job,
limitados aos repositorios autorizados e revogados no fim. Nao precisa de
Actions write, pois nao ha disparos nem commits nos repositorios de origem.

Os resultados de todos os builds e deploys aparecem no Actions do kairos-infra.

## Recursos novos, existentes e planos destrutivos

Terraform cria recursos ausentes e atualiza os que ja gerencia no estado. Recursos
existentes fora do estado precisam de importacao antes do primeiro apply.
O pipeline bloqueia planos com delete, inclusive substituicoes create/delete.
Mudancas destrutivas exigem manutencao e um plano manual revisado; nao ha flag
para ignorar essa protecao na Action. Nao executar `terraform destroy` no fluxo.

O plano aplicado e o mesmo artefato gerado para o commit de main. Artefatos duram
um dia; proteger acesso ao repo porque planos Terraform podem conter dados do estado.
Execucoes sao serializadas, usam lock S3 e recusam commits superados na main.

## Runner privado

E possivel criar a maquina pelo Terraform adicionando ao JSON:

```json
"provision_deployment_runner": true,
"deployment_runner_ami_id": "ami-ID-REAL-AMAZON-LINUX-2023-X86-64"
```

Escolher AMI na mesma regiao, com SSM e AWS CLI v2. A maquina fica em subnet privada,
sem IP publico ou porta SSH, com disco criptografado e IMDSv2. Sua instance role
permite SSM e nao administra o cluster. O output deployment_runner_instance_id
permite acessar via Session Manager e registrar o runner como usuario kairos-runner.
Instalar o runner seguindo Settings > Actions > Runners, verificar `aws --version`
e usar labels `self-hosted,linux,x64,kairos-eks`. Registrar como runner da organizacao
com grupo restrito ao kairos-infra.
Nunca disponibiliza-lo para jobs de PR nao confiaveis.

O registro GitHub e realizado separadamente; tokens de registro nao entram no
Terraform. No primeiro apply, manter KAIROS_PLATFORM_ENABLED=false; registrar
o runner e so entao ativar essa variable e executar provision.yml novamente.

## Verificacao de aplicacao e rollout

O release verifica plataforma, versao atual do segredo e commit de main. Compara
o manifesto desejado com o release Helm e registra `install`, `update` ou `current`
no resumo da Action. Depois executa Helm para reconciliar tambem drift dos objetos
vivos. Um manifesto inalterado nao exige reiniciar os pods.

O mobile usa duas replicas em nos distintos, maxUnavailable=0, maxSurge=1,
readiness estavel, PDB, espera antes de encerrar, shutdown graceful e drenagem ALB.
O upgrade espera a disponibilidade e reverte o release em falha. Reserva de capacidade
e necessaria: durante o rollout, a afinidade pode exigir um terceiro no.

A PR da API serializa o DDL de auditoria com lock transacional PostgreSQL, evitando
conflitos entre replicas. Ainda e recomendavel migrar esse DDL para migracoes
versionadas e manter futuras migracoes compativeis com ambas as versoes da API.
Rollback Helm nao desfaz mudancas no banco. Falhas de dependencias ou capacidade
podem causar indisponibilidade mesmo com esse rollout.

Para executar a verificacao central: Actions > Deploy connected services > Run workflow.
Os jobs da matriz identificam cada API. O SHA mais recente da main e validado
novamente antes de implantar. Imagens existentes sao reutilizadas por digest.
