"""Read-only PostgreSQL preflight from EKS using CSI-mounted credentials, never CI env."""
import argparse
import json
import subprocess
from diagnostics import kube, summary, error_lines

# Tables managed by the principal API's initial migration. An empty database may
# be initialized by Flyway; a baselined partial database must fail before Helm.
TABLES = {"companies", "users", "sectors", "aisles", "shelves", "employees",
          "inventories", "inventory_employees", "shelf_employees", "employee_aisles",
          "categories", "products", "product_shelves", "product_inventories",
          "restockings", "alerts", "customers", "purchases", "purchase_products", "audits"}

SQL = """SELECT json_build_object(
 'database',current_database(), 'schema',current_schema(),
 'tls',coalesce((SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()),false),
 'max',current_setting('max_connections')::int,
 'reserved',current_setting('superuser_reserved_connections')::int +
            coalesce(current_setting('reserved_connections',true),'0')::int,
 'used',(SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' OR (backend_type IS NULL AND datid IS NOT NULL)),
 'role_limit',(SELECT rolconnlimit FROM pg_roles WHERE rolname=current_user),
 'role_used',(SELECT count(*) FROM pg_stat_activity WHERE usename=current_user AND (backend_type='client backend' OR backend_type IS NULL)),
 'db_limit',(SELECT datconnlimit FROM pg_database WHERE datname=current_database()),
 'db_used',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND (backend_type='client backend' OR backend_type IS NULL)),
 'tables',coalesce((SELECT json_agg(tablename) FROM pg_tables WHERE schemaname='public'),'[]'::json),
 'history_present',to_regclass('public.flyway_schema_history') IS NOT NULL);"""

HISTORY = """SELECT json_build_object('history',coalesce(json_agg(json_build_object(
 'version',version,'success',success)),'[]'::json)) FROM public.flyway_schema_history;"""


class PreflightError(ValueError):
    """Only controlled messages without driver errors or credential data."""


def validate(report, expected, pool):
    if report.get("database") != expected or report.get("schema") != "public":
        raise PreflightError("Banco/schema inesperado. Confira DB_URL e o banco de producao.")
    if report.get("tls") is not True:
        raise PreflightError("A conexao PostgreSQL precisa usar TLS.")
    tables = set(report.get("tables", []))
    if tables and (not TABLES <= tables or not report.get("history_present")):
        raise PreflightError("Schema parcial ou sem historico Flyway; corrija o banco antes do deploy.")
    if any(not row.get("success") for row in report.get("history", [])):
        raise PreflightError("O banco contem migracao Flyway sem sucesso.")
    if any(row.get("version") == "3" for row in report.get("history", [])) and not {
            "restocking_history_delivery", "restocking_history_bypass"} <= tables:
        raise PreflightError("Historico Flyway V3 nao corresponde as tabelas existentes.")
    # The preflight connection closes before the application starts. Its slot is
    # discounted; reserve one additional slot for operations while the pool grows.
    available = report["max"] - report["reserved"] - (report["used"] - 1)
    for limit, used in (("role_limit", "role_used"), ("db_limit", "db_used")):
        if report[limit] >= 0:
            available = min(available, report[limit] - (report[used] - 1))
    if pool < 1 or available < pool + 1:
        raise PreflightError("Conexoes insuficientes para o novo pool e uma vaga operacional. "
                         "Feche clientes externos ou execute a transicao inicial documentada.")
    return available


def pod_spec(namespace):
    # psql reads credentials ONLY from CSI files. They never enter runner logs,
    # manifests, CLI arguments, or the Kubernetes env Secret cache.
    shell = r"""set -eu
uri=$(cat /mnt/secrets-store/DB_URL)
case "$uri" in jdbc:postgresql://*) uri=${uri#jdbc:};; *) exit 2;; esac
case "$uri" in *@*|*password=*|*user=*|*sslmode=disable*|*sslmode=allow*|*sslmode=prefer*) exit 2;; esac
case "&${uri#*\?}&" in *"&sslmode=require&"*|*"&sslmode=verify-ca&"*|*"&sslmode=verify-full&"*) ;; *) exit 2;; esac
export PGUSER="$(cat /mnt/secrets-store/DB_USERNAME)"
export PGPASSWORD="$(cat /mnt/secrets-store/DB_PASSWORD)"
export PGCONNECT_TIMEOUT=10 PGAPPNAME=kairos-preflight
export PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000'
psql "$uri" -X -qAt --no-password -v ON_ERROR_STOP=1 -c "$PREFLIGHT_SQL"
history=$(psql "$uri" -X -qAt --no-password -v ON_ERROR_STOP=1 -c "SELECT to_regclass('public.flyway_schema_history') IS NOT NULL")
if [ "$history" = t ]; then
 psql "$uri" -X -qAt --no-password -v ON_ERROR_STOP=1 -c "$HISTORY_SQL"
fi
"""
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {
        "name": "kairos-database-preflight", "namespace": namespace}, "spec": {
        "restartPolicy": "Never", "activeDeadlineSeconds": 180,
        "serviceAccountName": "kairos-runtime", "automountServiceAccountToken": False,
        "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{"name": "preflight", "image": "postgres:18-alpine",
            "command": ["/bin/sh", "-ec", shell],
            "env": [{"name": "PREFLIGHT_SQL", "value": SQL}, {"name": "HISTORY_SQL", "value": HISTORY}],
            "resources": {"requests": {"cpu": "50m", "memory": "64Mi"},
                          "limits": {"cpu": "250m", "memory": "128Mi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]}},
            "volumeMounts": [{"name": "runtime", "mountPath": "/mnt/secrets-store", "readOnly": True}]}],
        "volumes": [{"name": "runtime", "csi": {"driver": "secrets-store.csi.k8s.io", "readOnly": True,
                     "volumeAttributes": {"secretProviderClass": "mobile-api-database-preflight"}}}]}}


def render_object(namespace, values, overrides, template):
    rendered = subprocess.run(["helm", "template", "mobile-api", "charts/kairos-api", "-n", namespace,
                               "-f", values, "-f", overrides, "--show-only", "templates/" + template],
                              check=True, capture_output=True, text=True)
    converted = subprocess.run(["kubectl", "create", "--dry-run=client", "--validate=false", "-f", "-", "-o", "json"],
                               input=rendered.stdout, check=True, capture_output=True, text=True)
    return json.loads(converted.stdout)


def prepare_probe_resources(namespace, values, overrides):
    account = render_object(namespace, values, overrides, "serviceaccount.yaml")
    # On a cold install Helm has not created the runtime SA yet. Adoptable
    # metadata lets the subsequent Helm install manage it normally.
    current = kube(namespace, "get", "serviceaccount", account["metadata"]["name"],
                   "--ignore-not-found=true", "-o", "json")
    if not current.stdout.strip():
        account["metadata"].setdefault("annotations", {}).update({
            "meta.helm.sh/release-name": "mobile-api", "meta.helm.sh/release-namespace": namespace})
        subprocess.run(["kubectl", "-n", namespace, "create", "-f", "-"],
                       input=json.dumps(account), capture_output=True, text=True, check=True)
    provider = render_object(namespace, values, overrides, "secrets.yaml")
    provider["metadata"] = {"name": "mobile-api-database-preflight", "namespace": namespace}
    # No secretObjects: this probe does not rewrite the application's cached env Secret.
    provider["spec"].pop("secretObjects", None)
    provider["spec"]["parameters"]["objects"] = json.dumps([{
        "objectName": "kairos/production/mobile-api", "objectType": "secretsmanager",
        "jmesPath": [{"path": '"' + key + '"', "objectAlias": key, "filePermission": "0444"}
                    for key in ("DB_URL", "DB_USERNAME", "DB_PASSWORD")]}])
    subprocess.run(["kubectl", "-n", namespace, "apply", "-f", "-"],
                   input=json.dumps(provider), capture_output=True, text=True, check=True)


def run(namespace, expected, values, overrides):
    config = render_object(namespace, values, overrides, "configmap.yaml")
    pool = int(config["data"]["SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE"])
    name = "kairos-database-preflight"
    kube(namespace, "delete", "pod", name, "--ignore-not-found=true", "--wait=true")
    try:
        prepare_probe_resources(namespace, values, overrides)
        subprocess.run(["kubectl", "-n", namespace, "apply", "-f", "-"],
                       input=json.dumps(pod_spec(namespace)), check=True, capture_output=True, text=True)
        # Detect Failed promptly, instead of waiting the entire readiness timeout.
        import time
        for attempt in range(40):
            pod = json.loads(kube(namespace, "get", "pod", name, "-o", "json").stdout)
            phase = pod.get("status", {}).get("phase")
            if phase == "Succeeded":
                break
            if phase == "Failed":
                raise PreflightError("Preflight PostgreSQL falhou: confira acesso, TLS e vagas no banco.")
            time.sleep(5)
        else:
            raise PreflightError("Preflight PostgreSQL nao iniciou no prazo; consulte os eventos do pod.")
        report = {}
        for line in kube(namespace, "logs", name).stdout.splitlines():
            report.update(json.loads(line))
        available = validate(report, expected, pool)
        print(f"PostgreSQL: destino/schema/TLS/Flyway verificados; {available} vagas para pool de {pool}.")
    except (subprocess.SubprocessError, ValueError, KeyError) as error:
        print("\n".join(summary(namespace, pod_name=name)))
        print("\n".join(error_lines(namespace, name)))
        # Never echo psql output/errors: credentials remain inside the pod.
        if isinstance(error, PreflightError):
            raise
        raise PreflightError("Preflight PostgreSQL reprovado; revise banco/schema, TLS e capacidade antes de repetir.") from None
    finally:
        kube(namespace, "delete", "pod", name, "--ignore-not-found=true", check=False)
        kube(namespace, "delete", "secretproviderclass", "mobile-api-database-preflight",
             "--ignore-not-found=true", check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for option in ("namespace", "expected", "values", "overrides"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args()
    try:
        run(args.namespace, args.expected, args.values, args.overrides)
    except ValueError as error:
        raise SystemExit(str(error)) from None
