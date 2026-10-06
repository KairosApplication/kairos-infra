# Instalacao

Esta instalacao habilita somente a API do mobile. A segunda API continua como
modelo ate ficar pronta. Os comandos abaixo sao para Bash (Linux, macOS ou WSL);
Terraform tambem pode ser executado no PowerShell.

## 1. Preparar os valores e as ferramentas

Instalar AWS CLI v2, Terraform 1.13.5, kubectl compativel com Kubernetes 1.35,
Helm 3.19.0 e Python 3.12. Autenticar na AWS, preferencialmente por IAM Identity
Center/SSO, e conferir a conta:

```sh
aws sts get-caller-identity
```

Escolher conta, regiao, nome do cluster e o dominio publico da API.
O principal que cria a infraestrutura precisa conseguir administrar
VPC, EC2, EKS, IAM, ECR, Secrets Manager, S3 e CloudWatch, incluindo as roles
de servico exigidas pelo EKS. As roles de deploy das APIs recebem permissoes
restritas automaticamente; nao usar essas roles para provisionar o cluster.

Preparar um ARN IAM de administrador que voce consiga assumir. Informar esse
ARN em cluster_admin_principal_arns, evitando o ARN temporario de uma sessao STS.
A criacao do cluster nao concede acesso administrativo implicito ao criador.

## 2. Criar o armazenamento de estado

```sh
cp terraform/bootstrap/terraform.tfvars.example terraform/bootstrap/terraform.tfvars
# Editar conta, regiao e nome globalmente unico do bucket.
terraform -chdir=terraform/bootstrap init
terraform -chdir=terraform/bootstrap plan -out=bootstrap.tfplan
terraform -chdir=terraform/bootstrap apply bootstrap.tfplan
```

Manter o terraform.tfstate do bootstrap em armazenamento privado e com backup.
Ele e local e fica ignorado pelo Git. O bucket de estado tem versionamento,
criptografia, bloqueio de acesso publico e protecao contra destruicao.

## 3. Provisionar EKS e recursos das APIs habilitadas

```sh
cp terraform/production/backend.hcl.example terraform/production/backend.hcl
cp terraform/production/terraform.tfvars.example terraform/production/terraform.tfvars
# Editar os dois arquivos antes de continuar.
terraform -chdir=terraform/production init -backend-config=backend.hcl
terraform -chdir=terraform/production plan -out=production.tfplan
terraform -chdir=terraform/production apply production.tfplan
terraform -chdir=terraform/production output -json services
```

O backend usa S3 com lockfile. Os operadores precisam de acesso de leitura/escrita
ao objeto production/terraform.tfstate e ao objeto de lock associado. O estado,
tfvars locais e planos nao devem ser enviados ao GitHub.

cluster_public_access_cidrs deve conter o IP publico real do operador em /32.
O endpoint privado permanece habilitado para o runner. Se a conta ja possui
o provider token.actions.githubusercontent.com, configurar github_oidc_provider_arn
com seu ARN em vez de tentar criar um segundo provider.

Apenas mobile-api deve constar de services por enquanto. Os outputs mostram
o repositorio ECR, as roles publisher/deployer/runtime e o nome do segredo.

## 4. Conectar PostgreSQL e Redis

No AWS Secrets Manager, preencher o segredo criado pelo Terraform:
kairos/production/mobile-api. Seu valor deve ser um JSON com estas quatro chaves:

```json
{
  "DB_URL": "jdbc:postgresql://HOST:PORTA/BANCO?sslmode=require",
  "DB_USERNAME": "USUARIO_DA_API",
  "DB_PASSWORD": "SENHA_REAL",
  "REDIS_URL": "rediss://USUARIO:SENHA@HOST:PORTA"
}
```

Usar o console ou uma ferramenta autorizada para preencher os valores;
nao versionar um arquivo contendo esse JSON real. O Terraform cria somente
os metadados do segredo, mantendo as senhas fora do estado Terraform.

O banco existente pode continuar no Aiven. Se houver allowlist no provedor,
liberar o IP de saida do NAT Gateway para o acesso da API. O Redis deve ser um
servico acessivel do cluster, com autenticacao e TLS. Portas e URLs precisam
corresponder ao provedor real; Redis localhost nao funciona nos pods.

## 5. Instalar a base Kubernetes

Como um dos administradores listados no Terraform:

```sh
export AWS_REGION=REGIAO_ESCOLHIDA
export EKS_CLUSTER_NAME=kairos-production
bash scripts/bootstrap-platform.sh
```

Esse script cria o namespace mobile, a IngressClass do Auto Mode, habilita o
controller de politicas de rede e instala o driver/provider de segredos.
Tambem cria uma Role/RoleBinding complementar para SecretProviderClass;
a policy EKS Edit cobre os recursos Kubernetes padrao, mas nao esse CRD.

Verificar os pods do driver em kube-system antes do primeiro deploy:

```sh
kubectl get pods -n kube-system
kubectl get csidriver secrets-store.csi.k8s.io
kubectl get ingressclass kairos-public
```

## 6. Preparar dominio e HTTPS

Solicitar no AWS Certificate Manager um certificado para o dominio da API,
na mesma regiao do ALB. Concluir a validacao DNS e guardar seu ARN.
O chart exige certificado valido e dominio para criar a entrada publica.

Apos o primeiro deploy, obter o hostname do ALB:

```sh
kubectl get ingress mobile-api -n kairos-mobile-api
```

Criar o registro DNS do dominio apontando para esse hostname (Alias no Route 53
ou CNAME conforme o provedor). O DNS e o certificado sao configurados
separadamente porque o dominio e a zona ainda nao foram informados.

## 7. Preparar o runner de deploy

O build executa em runner GitHub hospedado. O deploy precisa de um runner Linux
com acesso ao endpoint privado do EKS, por exemplo uma maquina na VPC
com acesso de saida via NAT. Instalar AWS CLI v2 e disponibilizar ferramentas
basicas exigidas pelas actions, incluindo Node, Python e tar.

Usar uma subnet de private_subnet_ids e anexar a maquina o security group
deployment_runner_security_group_id dos outputs Terraform. Esse grupo possui
saida HTTPS e uma regra correspondente no security group do cluster para
acessar o endpoint privado na porta 443. Administrar a maquina por um mecanismo
privado, como SSM, configurado separadamente; nao ha porta SSH publica aberta.

Registrar um runner dedicado com labels self-hosted, linux, x64 e kairos-eks
e limitar seu uso ao repositorio confiavel da API. Ele recebe credenciais
AWS temporarias por OIDC; nao precisa de credenciais AWS permanentes nem de uma
instance profile com acesso administrativo ao cluster.

O runner nao e provisionado por este repo porque registro e acesso dependem
da configuracao da organizacao GitHub. Sem ele, o job de deploy ficara na fila.
Um runner fora da VPC precisa de conectividade privada equivalente, como VPN.

## 8. Conectar o repositorio da API

No kairos-springboot:

1. Copiar examples/mobile-api/deploy.yml para .github/workflows/deploy.yml.
2. O workflow usa o Dockerfile da API se existir; caso contrario, usa o
   Dockerfile Java 21 deste repo. A CI da API deve continuar chamada CI.
3. Criar um GitHub Environment production, restringir deploys a main e
   configurar aprovacao se desejado. A restricao a main e necessaria porque
   o subject OIDC de ambientes nao inclui a branch.
4. Cadastrar estas repository variables em Settings > Secrets and variables > Actions.

| Variable | Valor |
|---|---|
| AWS_REGION | Regiao escolhida |
| AWS_ACCOUNT_ID | ID da conta com 12 digitos |
| EKS_CLUSTER_NAME | Nome do cluster |
| AWS_PUBLISHER_ROLE_ARN | publisher_role_arn do output services |
| AWS_DEPLOYER_ROLE_ARN | deployer_role_arn do output services |
| API_HOST | Dominio da API, sem https:// |
| API_CERTIFICATE_ARN | ARN ACM do certificado validado |
| KAIROS_DEPLOY_ENABLED | true somente depois de concluir os passos anteriores |

O workflow da API chama reusable-release.yml deste repo. Em main, uma CI
bem-sucedida dispara o release do mesmo SHA. O release tambem executa verify
com PostgreSQL antes de publicar, inclusive na execucao manual.

Por padrao, o chamador e o checkout de infraestrutura usam main. Para fixar
uma revisao revisada da infraestrutura, substituir @main e infra-ref pelo
mesmo SHA do kairos-infra. Atualizar esse SHA quando quiser consumir alteracoes
do chart ou pipeline. Os dois devem apontar para a mesma revisao.

No GitHub Actions, confirmar que a politica da organizacao permite actions
e workflows reutilizaveis deste repo. O workflow nao precisa de PAT para
editar outro repositorio.

## 9. Conferir o primeiro release

```sh
kubectl get pods,svc,ingress -n kairos-mobile-api
kubectl rollout status deployment/mobile-api -n kairos-mobile-api
curl --fail https://DOMINIO_DA_API/health
```

Testar login, persistencia da sessao e uma chamada autenticada pelo mobile.
A API atual usa sessao e CSRF; o cliente deve preservar cookies e seguir o
fluxo de autenticacao existente. Um endpoint /health pronto nao substitui
essa verificacao funcional.

O repositorio de infra pode ser publicado e validado antes destes passos.
Publicar arquivos no GitHub nao provisiona AWS nem ativa o deploy da API.
