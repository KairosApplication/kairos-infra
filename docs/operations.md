# Operacao

## Release e rollback

Uma alteracao em main da API, apos CI bem-sucedida, gera uma imagem com a tag
do SHA do codigo. O ECR protege a tag contra sobrescrita. O deploy usa o digest
sha256 da imagem e espera os pods ficarem prontos. Um commit que deixou de ser
a revisao atual da main nao e implantado por um workflow atrasado.

Helm --atomic tenta retornar a ultima revisao bem-sucedida quando um upgrade
falha. No primeiro install, a falha remove a release; nao existe revisao anterior.
Nao ha reversao automatica de migracoes do banco.

Para rollback operacional, com acesso autorizado:

```sh
helm history mobile-api -n kairos-mobile-api
helm rollback mobile-api NUMERO_DA_REVISAO -n kairos-mobile-api --wait --timeout 15m
```

Sempre avaliar a compatibilidade do esquema do banco antes de reverter.
Aplicar migracoes compativeis com a versao anterior durante um rolling update;
remocoes de campos devem ocorrer em uma etapa posterior.

## Segredos

Cada service account kairos-runtime recebe uma role Pod Identity limitada
ao segredo da propria API. O CSI monta as chaves e sincroniza um Secret Kubernetes
usado como variaveis de ambiente. O provider recebe permissoes via Pod Identity,
sem access key na imagem ou no chart.

A rotacao atualiza arquivos e o Secret, mas variaveis de ambiente ja carregadas
na JVM nao mudam. Apos mudar DB_PASSWORD ou REDIS_URL e confirmar a sincronizacao,
reiniciar os pods de forma gradual:

```sh
kubectl rollout restart deployment/mobile-api -n kairos-mobile-api
kubectl rollout status deployment/mobile-api -n kairos-mobile-api
```

O Secret sincronizado depende de pelo menos um pod montando o volume.
Nao usa-lo como fonte independente para outro workload.
Nunca imprimir seu conteudo em logs de diagnostico.

## Escala

O deploy mobile usa duas replicas em nos separados e cria um PDB.
A afinidade obrigatoria exige capacidade para dois nos e pode exigir um terceiro
durante o rollout com maxSurge=1. Nao reduzir para uma replica esperando tolerancia
a falha de no.

Integrar a PR da API com lock transacional no PostgresAuditInitializer antes
de ativar o deploy. Redis compartilha sessoes entre replicas. Planejar a migracao
futura do DDL de auditoria para Flyway e testar login/sessoes durante o rollout.

Para HPA, instalar um metrics-server
compativel com a versao EKS e confirmar kubectl top pods antes de habilitar
autoscaling.enabled. Ajustar minReplicas, maxReplicas e CPU a partir de medicao,
incluindo o limite de conexoes PostgreSQL por replica.

O Auto Mode escala nos de acordo com os pods; o HPA escala a quantidade de pods.
Nao habilitar HPA antes de instalar a fonte de metricas.

## Diagnostico

```sh
kubectl get events -n kairos-mobile-api --sort-by=.lastTimestamp
kubectl describe pod NOME_DO_POD -n kairos-mobile-api
kubectl logs deployment/mobile-api -n kairos-mobile-api --tail=100
```

- Pending: verificar capacidade, requests e NodePools do Auto Mode.
- FailedMount: verificar valor do segredo, chaves JSON, Pod Identity, role
  runtime e driver CSI em kube-system.
- Forbidden em SecretProviderClass: executar o bootstrap RBAC como administrador.
- Falha no health: verificar conectividade PostgreSQL/Redis e inicializacao.
- Deploy na fila: verificar runner kairos-eks registrado e disponivel.
- Timeout do kubectl: verificar conectividade do runner ao endpoint privado.
- ALB sem HTTPS: conferir certificado ACM na regiao correta, DNS e IngressClass.

Os logs CloudWatch provisionados sao do control plane. Para os logs da API,
kubectl logs e a fonte inicial; instalar um coletor para retencao centralizada.

## Alteracoes de infraestrutura

Revisar terraform plan antes de aplicar alteracoes. O cluster tem deletion_protection
e o bucket tem prevent_destroy. Remover essas protecoes exige uma alteracao
explicita de configuracao. Para uma desmontagem planejada, remover primeiro
as releases/Ingresses para permitir ao EKS excluir os ALBs; preservar
PostgreSQL, Redis e backups conforme a politica do projeto.

A versao Kubernetes esta fixada em 1.35. Consultar o calendario EKS antes
de upgrades. Atualizar os testes, o cliente kubectl, a configuracao do cluster
e os providers de forma coordenada.
