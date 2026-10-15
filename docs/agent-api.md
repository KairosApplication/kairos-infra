# Futura API consumida pelo agente

Esta e uma API separada da API mobile. O agente de IA e o consumidor;
este repo nao cria um agente nem escolhe seu provedor de IA.

A API do agente esta desabilitada em services.json e nao consta da configuracao
Terraform inicial. Seu modelo Helm nao cria Ingress publico.

Para habilitar quando a aplicacao estiver pronta:

1. Confirmar o repositorio real, Dockerfile, comando de testes, porta e endpoint
   de prontidao. O modelo usa porta 8080 e /health, que devem ser ajustados.
2. Ajustar a imagem para funcionar com usuario 10001 e filesystem somente leitura,
   ou revisar o chart para o runtime real.
3. Informar source_repository e enabled: true para agent-api em services.json.
   Atualizar o teste de APIs habilitadas para refletir essa ativacao.
4. Adicionar agent-api em services no terraform.tfvars, com o mesmo namespace
   kairos-agent-api, e aplicar o plano revisado.
5. Aplicar platform/agent-namespaces.yaml e executar scripts/bootstrap-rbac.py
   como administrador para criar as permissoes complementares de deploy.
6. Preencher o segredo kairos/production/agent-api e revisar secrets.keys
   em environments/production/agent-api.yaml. AGENT_API_TOKEN e apenas um
   nome de exemplo, nao uma autenticacao ja implementada.
7. Configurar o servico em DEPLOY_CONFIG_JSON do kairos-infra e habilitar
   somente depois de testar a API. Nao instalar chamador de deploy na API.


O endereco interno sera:

```text
http://agent-api.kairos-agent-api.svc.cluster.local
```

A NetworkPolicy permite consumidores no namespace kairos-agent-client
com label app.kubernetes.io/name: kairos-agent. O controller de politicas de rede
precisa estar habilitado, conforme o bootstrap. Verificar em um cluster real
que uma chamada de um namespace nao autorizado e bloqueada antes de liberar uso.

A API ainda precisa implementar autenticacao de servico e autorizacao das
operacoes do agente. Acesso privado nao substitui essas verificacoes.

Se o agente rodar fora do cluster, decidir a conectividade: rede privada/VPN
ou uma entrada externa autenticada e com TLS. O modelo atual aceita o primeiro
cenario e precisa de ajuste para o segundo. Nao habilitar um Ingress publico
sem definir essa autenticacao.

## Atualizacao independente

Cada API recebe namespace, imagem ECR, roles de publicacao/deploy e segredo
proprios. Uma release de mobile-api nao altera a imagem de agent-api.
Elas compartilham apenas o cluster e a rede.
