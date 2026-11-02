# Publicar ou atualizar as APIs no EKS

## Workflow principal

**Actions > Deploy APIs to EKS > Run workflow > main**

Depois de integrar uma correcao, iniciar uma **nova execucao** na main. `Re-run`
preserva o SHA anterior e nao carrega a nova configuracao. O fluxo rejeita uma
revisao de infraestrutura superada antes de preparar roles ou provisionar recursos.

### Primeira troca do pool PostgreSQL

Na primeira execucao com o pool menor, marcar `initial-pool-transition` somente
se aceitar uma breve indisponibilidade da principal. A opcao vem desmarcada.
Ela chega apenas ao deploy mobile-api: encerra as replicas antigas, espera a
liberacao das conexoes, verifica o banco e instala a configuracao nova. Se o
preflight falhar, tenta restaurar a quantidade anterior de replicas. A opcao
nao deve ser marcada nas atualizacoes seguintes; elas mantem `maxUnavailable=0`.
Nao cancelar o job durante a troca: o encerramento abrupto do runner pode impedir
a restauracao. A opcao nao resolve um release Helm que ja esteja pendente;
esse estado exige recuperacao antes de iniciar a troca.

### Verificacoes e diagnostico do banco

Antes do Helm da principal, um pod temporario usa psql e a identidade runtime
no mesmo EKS. Le DB_URL, DB_USERNAME e DB_PASSWORD em arquivos CSI; os valores
nao passam pelo ambiente ou logs do runner. Confere banco `kairosdb`, schema
public, TLS, tabelas/historico Flyway e vagas globais/por usuario/por banco para
o novo pool e uma conexao operacional. `MOBILE_API_DATABASE_NAME` e uma Variable
opcional para mudar o nome esperado. Banco vazio pode ser inicializado pelo
Flyway; schema parcial e historico com falha reprovam antes do rollout.
O teste usa a conexao em modo somente leitura e remove pod/provider temporarios.
Em instalacao nova, prepara o ServiceAccount runtime com metadados de adocao
Helm, sem criar uma nova role ou ampliar suas permissoes.

O job reserva 40 minutos para preparo, preflight, ate 15 minutos de atualizacao
e outros 15 de rollback. O timeout de prontidao Helm continua em 15 minutos.
Durante o rollout, coleta estados, motivos de eventos e assinaturas de erro
antes de o rollback remover o pod. As mensagens da aplicacao nao sao copiadas
integralmente: apenas classes de excecao e assinaturas conhecidas sao publicadas.
O artefato de diagnostico fica disponivel por 3 dias se o rollout falhar.
O teste de integracao Redis tambem coleta diagnosticos antes de remover seu pod.

Secrets sem mudanca nao geram outra versao. Ao reverter uma configuracao antiga,
a sincronizacao cria uma nova versao corrente em vez de reutilizar um token
historico que deixaria AWSCURRENT apontando para outra configuracao.

O preflight e uma verificacao pontual, nao uma reserva de conexoes. Outros
clientes ainda precisam respeitar o limite compartilhado da Aiven.

Arquivo: .github/workflows/deploy-apis.yml. Executa os workflows locais na mesma
execucao do GitHub Actions e espera seus resultados. Nao dispara workflows em
outros repositorios e nao considera um disparo como deploy concluido.

## Ordem de execucao

1. **Check deployment setup**: confere branch, JSON, nomes, conta/regiao e presenca
   da autenticacao, sem chamadas nem mudancas AWS.
2. Em paralelo, executa os workflows existentes:
   - Repository validation: sintaxe/estrutura dos arquivos;
   - Validate infrastructure: Terraform simulado, Helm, scripts e API Redis;
   - Secret scan: procura segredos expostos no historico.
3. Somente se todas as validacoes passarem, chama **Complete EKS deployment**:
   bootstrap -> Terraform plan/apply -> runner e segredos -> plataforma Kubernetes
   -> testes/build/publicacao -> releases Helm -> verificacao privada final.
4. Publica um resumo; falha, cancelamento ou etapa obrigatoria pulada impedem
   que o fluxo seja apresentado como concluido.

O codigo Java e testado no release antes de publicar uma imagem nova. O teste
de API Redis da validacao nao substitui a verificacao do SHA exato no release.

## Aplicacao nova e aplicacao existente

E o mesmo botao para os dois casos:

- Terraform cria recursos ausentes no estado ou atualiza os recursos gerenciados.
- Recursos AWS existentes fora do estado precisam de importacao previamente.
- Cada release e classificado como install, update ou current.
- Helm upgrade --install cria ou atualiza o release e reconcilia drift.
- Imagens existentes sao reutilizadas por SHA/digest. Pods nao precisam reiniciar
  quando imagem, configuracao e versao do segredo continuam iguais.
- Exclusoes/substituicoes destrutivas continuam bloqueadas.
- Readiness e --atomic --wait controlam o rollout e a tentativa de rollback.
  Rollback Helm nao desfaz banco, infraestrutura criada ou outro servico.

## Preparacao inicial

Reutiliza a configuracao de [full-deploy.md](full-deploy.md). Ainda sao necessarios
conta/regiao, bucket escolhido, JSONs de configuracao, identidade AWS inicial,
GitHub App do runner e PostgreSQL existente. Com entrypoint=cloudfront, a URL
HTTPS e o certificado sao fornecidos pela AWS; com dominio proprio, exigir ACM validado.
O workflow verifica a presenca do par de Secrets AWS ou de uma role OIDC.
Nao colocar valores de credenciais no YAML ou em Variables.

Os Environments podem pedir aprovacao de um revisor. O workflow respeita essa
pausa. Com a configuracao preparada, nao e preciso executar os outros workflows
manualmente. As flags KAIROS_INFRA_ENABLED/KAIROS_PLATFORM_ENABLED/
KAIROS_RECONCILE_ENABLED nao sao necessarias nesse caminho completo.

As validacoes recebem apenas contents:read e nao recebem os Secrets AWS.
A permissao id-token:write e os Secrets sao encaminhados ao job de deploy.
As filas das validacoes separam a CI normal do workflow orquestrador para que
um push na main nao cancele as verificacoes de uma implantacao em andamento.

PostgreSQL externo continua sendo pre-requisito. DNS proprio e certificado ACM
sao necessarios apenas no modo custom-domain. No modo cloudfront, o fluxo
provisiona o endereco HTTPS gerenciado depois das APIs.
A integracao de negocio entre APIs precisa estar publicada na main da API
principal. O teste final do fluxo existente verifica rede/autenticacao/Redis.

## Operacao avancada

Complete EKS deployment, Plan and provision AWS infrastructure e Deploy connected
services continuam disponiveis para operacao individual. Deploy APIs to EKS
e o ponto de entrada recomendado quando se deseja validar e executar tudo.

## Validacao antes da publicacao

Este workflow pode ser conferido localmente com actionlint e os testes Python.
Isso nao executa a implantacao na AWS. Depois de revisar/publicar e integrar na
main, fazer a primeira execucao real com a configuracao inicial preenchida.
