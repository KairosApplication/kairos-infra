# Publicar ou atualizar as APIs no EKS

## Workflow principal

**Actions > Deploy APIs to EKS > Run workflow > main**

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
GitHub App do runner, PostgreSQL existente e certificado ACM validado.
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

DNS publico, certificado e PostgreSQL externo continuam sendo pre-requisitos.
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
