# API de dados para o agente de IA

Origem: KairosApplication/kairos-api-ia, Java 21/Spring Boot, MongoDB.
Cadastrada e habilitada como agent-api em services.json. Todo deploy ocorre
no kairos-infra; o repositorio da API nao precisa de um workflow de deploy.

## Acesso

Para o agente fora da AWS, configurar DEPLOY_CONFIG_JSON com:

```json
{
  "mobile-api": {"entrypoint":"cloudfront"},
  "agent-api": {"entrypoint":"cloudfront"}
}
```

Cada API tem URL propria https://....cloudfront.net, certificado AWS e ALB
privado. O fluxo cria/reutiliza as distribuicoes e publica as URLs no resumo.
Nao precisa comprar dominio ou emitir certificado ACM. As respostas nao sao
armazenadas no cache. Cookies, token Bearer, query strings e metodos HTTP sao
encaminhados. A API Redis continua privada dentro do EKS.

O GET /health e publico e verifica o MongoDB. Rotas /api/v1/** exigem
Authorization: Bearer <API_ACCESS_TOKEN>. O token e uma credencial de servico,
nao uma chave de modelo de IA nem login de usuario. O bootstrap gera um token
estavel no Secrets Manager; ele nao aparece em outputs ou logs.

## Conexao MongoDB

Secret GitHub AGENT_RUNTIME_SECRETS_JSON aceita uma URI MongoDB direta ou:

```json
{"MONGODB_URI":"mongodb+srv://...","MONGODB_DATABASE":"kairos_ai"}
```

Nao colocar URI real em arquivos versionados. Quando a URI direta nao inclui
banco, usa kairos_ai, o banco verificado documentado no repositorio da API.
Em JSON, configurar o banco explicitamente ou inclui-lo no caminho da URI.
API_ACCESS_TOKEN e opcional no JSON: se fornecido, deve ter 32+ caracteres.
Valores existentes no Secrets Manager sao preservados quando omitidos.

O fluxo valida a configuracao antes de provisionar e sincroniza somente os
segredos dessa API em kairos/production/agent-api. O pod usa identidade propria,
sem acesso aos segredos PostgreSQL. Se o provedor MongoDB restringir IPs, liberar
os IPs publicos /32 dos NATs AWS. Nao e preciso nem recomendado liberar 0.0.0.0/0.
A conectividade real/autenticacao sao verificadas pela inicializacao e readiness.

## Build e comportamento

A CI central executa mvnw clean verify com Java 21, sem o perfil postgres-tests.
O Dockerfile esta em examples/agent-api/Dockerfile e cria processo nao root.
A porta e 8081; o schema e as collections MongoDB precisam existir previamente.

Esta API gerencia os dados de IA existentes; nao executa inferencia/agentes.
Escritas permanecem desabilitadas conforme o padrao da API
(APP_MONGODB_WRITES_ENABLED=false). Habilitar CRUD exige revisar essa opcao e
as permissoes MongoDB para o banco desejado. O deploy nao altera os dados.

Executar Actions > Deploy APIs to EKS na main depois de revisar/integrar o codigo
e concluir Variables, Secrets e autenticacao AWS. Release por SHA/digest,
readiness e rollback Helm seguem o mesmo fluxo das demais APIs.
