"""
churn_pipeline_dag.py — ONE DAG, triggered once per student.

Students do not get their own DAG file. They open the Airflow UI, press
"Trigger DAG w/ config", and type:

    {"student_id": 7}

Every path and object name derives from that one number. Thirty students produce
thirty independent runs of this same DAG -- thirty rows in the Grid view, which is
the clearest picture of "what an orchestrator does" you will get all session.

THE SPEC BELOW IS NOT INVENTED. It is the SparkApplication that PCAI's Create
Spark Application wizard produced for a run that COMPLETED successfully, with only
the name and the arguments parameterised. Three details in it are easy to get
wrong and impossible to guess:

  * apiVersion is sparkoperator.HPE.com/v1beta2, not sparkoperator.k8s.io
  * three PVCs must be mounted (user, shared, spark-history event log)
  * the MapR sparkConf keys and imagePullSecret are required by this platform

WHY THE KUBERNETES CLIENT INSTEAD OF SparkKubernetesOperator
    The cncf.kubernetes provider assumes the upstream CRD group and changed its API
    across versions. Talking to the Kubernetes API directly avoids both problems;
    the only dependency is the `kubernetes` package, which Airflow already needs.
"""

from datetime import datetime, timedelta
import time

from airflow import DAG
from airflow.models.param import Param
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowFailException

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG — taken verbatim from the working SparkApplication
#
# The four cluster-specific values can be overridden WITHOUT editing this file:
# Airflow UI -> Admin -> Variables, or env vars AIRFLOW_VAR_LAB18_NAMESPACE etc.
# Read them off a SparkApplication that has actually COMPLETED on the cluster:
#     kubectl get sparkapplication <name> -n <ns> -o yaml
# ═══════════════════════════════════════════════════════════════════════════

from airflow.models import Variable

def _cfg(key, default):
    return Variable.get(f"lab18_{key}", default_var=default)

# PCAI launches every task pod inside the TRIGGERING USER's project namespace
# (event log: dag_deployed_in_user_ns). The SparkApplication must be created in that
# same namespace, as that same user -- a pod in project-user-alice cannot create
# objects in project-user-haris. So NAMESPACE and SPARK_USER are resolved AT RUN TIME
# from the pod itself; the values below are only parse-time defaults, overridable
# with Airflow Variables lab18_namespace / lab18_spark_user if a cluster needs it.
NAMESPACE       = _cfg("namespace",       "project-user-haris")
SPARK_IMAGE     = _cfg("spark_image",     "10.79.253.45/ezmeral-common/hpe-spark/spark:v3.5.5.2.1")
SERVICE_ACCOUNT = _cfg("service_account", "spark-runner")
PULL_SECRET     = "imagepull"
SPARK_USER      = _cfg("spark_user",      "haris")

SA_NS_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

def _runtime_target():
    """(namespace, spark_user) for THIS task pod. Falls back to the configured
    defaults when not running in Kubernetes (e.g. DAG parse on a laptop)."""
    try:
        ns = open(SA_NS_FILE).read().strip()
    except Exception:
        return NAMESPACE, SPARK_USER
    if not ns:
        return NAMESPACE, SPARK_USER
    user = ns[len("project-user-"):] if ns.startswith("project-user-") else SPARK_USER
    return ns, user

# Volume as SPARK sees it. The notebook sees the same files at ~/shared/...
SPARK_BASE = "/mounts/shared-volume/shared/data-engineering-lab"
APP_FILE   = f"local://{SPARK_BASE}/spark/curate_events.py"
RAW_PATH   = f"file://{SPARK_BASE}/raw/watch_events"
OUT_TMPL   = f"file://{SPARK_BASE}/curated/student-{{sid}}/watch_events"

POLL_SECONDS    = 10
TIMEOUT_MINUTES = 30

GROUP, VERSION, PLURAL = "sparkoperator.hpe.com", "v1beta2", "sparkapplications"

# All three PVCs are required: the job reads/writes `shared`, and the operator
# expects `user` and the history-server event log to be present.
VOLUMES = [
    {"name": "upv1", "persistentVolumeClaim": {"claimName": "user-pvc"}},
    {"name": "pv1", "persistentVolumeClaim": {"claimName": "kubeflow-shared-pvc"}},
    {"name": "sparkhs-eventlog-storage",
     "persistentVolumeClaim": {"claimName": "sparkhs-pvc"}},
]
MOUNTS_COMMON = [
    {"mountPath": "/mounts/shared-volume/user", "name": "upv1"},
    {"mountPath": "/mounts/shared-volume/shared", "name": "pv1"},
]
MOUNTS_DRIVER = MOUNTS_COMMON + [
    {"mountPath": "/opt/mapr/spark/sparkhs-eventlog-storage",
     "name": "sparkhs-eventlog-storage"},
]


# ═══════════════════════════════════════════════════════════════════════════

def _k8s():
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CustomObjectsApi(), client.CoreV1Api()


def _sid(context):
    """Read student_id from the trigger form (DAG params; a JSON conf still works
    because Airflow merges dag_run.conf into params). Fail loudly if absent -- an
    unparameterised run would silently overwrite student-00's output."""
    val = (context.get("params") or {}).get("student_id")
    if val is None:
        val = (context["dag_run"].conf or {}).get("student_id")
    if val is None or val == "":
        raise AirflowFailException(
            'No student_id supplied.\n'
            'Press the play button, enter your student number in the student_id '
            'field of the trigger form, then click Trigger.')
    n = int(val)
    if not 0 <= n <= 99:
        raise AirflowFailException(f"student_id {n} out of range (0-99)")
    return f"{n:02d}"


def build_spec(sid, namespace=None, spark_user=None):
    namespace  = namespace  or NAMESPACE
    spark_user = spark_user or SPARK_USER
    return {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "SparkApplication",
        "metadata": {
            "name": f"curate-student-{sid}",
            "namespace": namespace,
            "labels": {
                "hpe-ezua/app": "spark",
                "hpe-ezua/type": "app-service-user",
                "sidecar.istio.io/inject": "false",
                "student": sid,
            },
        },
        "spec": {
            "type": "Python",
            "mode": "cluster",
            "image": SPARK_IMAGE,
            "imagePullPolicy": "Always",
            "imagePullSecrets": [PULL_SECRET],
            "mainApplicationFile": APP_FILE,
            "arguments": [sid, RAW_PATH, OUT_TMPL.format(sid=sid)],
            "sparkVersion": "3.5.5",
            "restartPolicy": {"type": "Never"},
            "sparkConf": {
                "spark.eventLog.enabled": "true",
                "spark.eventLog.dir": "file:///opt/mapr/spark/sparkhs-eventlog-storage",
                "spark.executorEnv.SPARK_USER": spark_user,
                "spark.kubernetes.driverEnv.SPARK_USER": spark_user,
                "spark.mapr.user.secret": "hpe-autotix-generated-secret",
                "spark.mapr.user.secret.autogen": "true",
                "spark.ui.view.acls": namespace,
            },
            "volumes": VOLUMES,
            "driver": {
                "cores": 1, "coreLimit": "1", "memory": "4G",
                "serviceAccount": SERVICE_ACCOUNT,
                "labels": {"version": "3.5.5", "student": sid},
                "volumeMounts": MOUNTS_DRIVER,
            },
            "executor": {
                "cores": 1, "coreLimit": "1", "memory": "4G", "instances": 1,
                "labels": {"version": "3.5.5", "student": sid},
                "volumeMounts": MOUNTS_COMMON,
            },
        },
    }


def submit_and_wait(**context):
    sid = _sid(context)
    name = f"curate-student-{sid}"
    api, core = _k8s()
    ns, spark_user = _runtime_target()
    print(f"[dag] namespace {ns}   spark user {spark_user}")

    # Idempotency: a re-run replaces the old application rather than colliding.
    try:
        api.delete_namespaced_custom_object(GROUP, VERSION, ns, PLURAL, name)
        print(f"[dag] deleted previous {name}")
        time.sleep(5)
    except Exception:
        pass

    api.create_namespaced_custom_object(GROUP, VERSION, ns, PLURAL,
                                        build_spec(sid, ns, spark_user))
    print(f"[dag] submitted {name}")
    print(f"[dag]   reads  {RAW_PATH}")
    print(f"[dag]   writes {OUT_TMPL.format(sid=sid)}")

    deadline, last = time.time() + TIMEOUT_MINUTES * 60, None
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        obj = api.get_namespaced_custom_object(GROUP, VERSION, ns, PLURAL, name)
        state = obj.get("status", {}).get("applicationState", {}).get("state", "PENDING")
        if state != last:
            print(f"[dag] {time.strftime('%H:%M:%S')}  {state}")
            last = state

        if state == "COMPLETED":
            _tail_driver_log(core, name, ns)
            return f"{name} completed"

        if state in ("FAILED", "SUBMISSION_FAILED"):
            msg = obj.get("status", {}).get("applicationState", {}).get(
                "errorMessage", "(no message)")
            _tail_driver_log(core, name, ns)
            raise AirflowFailException(f"Spark job {state}: {msg}")

    raise AirflowFailException(f"timed out after {TIMEOUT_MINUTES} min in state {last}")


def _tail_driver_log(core, name, namespace, lines=40):
    """Surface the job's own summary in the Airflow log, so a student never has to
    go hunting in the Spark UI to find out whether their run was correct."""
    try:
        print(f"\n[dag] ---- driver log (last {lines} lines) ----")
        print(core.read_namespaced_pod_log(name=f"{name}-driver",
                                           namespace=namespace, tail_lines=lines))
    except Exception as e:
        print(f"[dag] could not read driver log: {e}")


default_args = {"owner": "instructor", "retries": 1,
                "retry_delay": timedelta(minutes=1)}

# PCAI enforces a policy that every DAG declares who may touch it; without this the
# scheduler reports "Unprotected DAG Detected" and refuses to load it.
#
# Note that TRIGGERING a DAG needs `can_edit`, not just `can_read` -- so participants
# must have both, or the Trigger button does nothing for them. They deliberately do
# NOT get `can_delete`: 30 people should be able to run this DAG, not remove it.
ACCESS_CONTROL = {
    "Admin": {"can_read", "can_edit", "can_delete"},
    "All":   {"can_read", "can_edit"},
}

with DAG(
    dag_id="churn_pipeline",
    description='Curate one student\'s watch_events with Spark. Trigger with {"student_id": N}',
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule=None,          # students trigger it; never on a timer
    catchup=False,
    max_active_runs=40,     # all 30 must SEE their run start, not queue invisibly
    access_control=ACCESS_CONTROL,
    tags=["lab", "spark", "churn"],
    # Declaring a param is what makes Airflow >= 2.9 show a trigger FORM when the
    # play button is pressed. Without params the button runs the DAG immediately
    # with no chance to enter anything.
    params={
        "student_id": Param(
            None, type=["null", "integer"], minimum=0, maximum=99,
            title="Student number",
            description="Your student number, 0-99, without leading zeros. "
                        "Every output path and object name derives from it."),
    },
) as dag:

    PythonOperator(
        task_id="curate",
        python_callable=submit_and_wait,
        pool="spark_pool",  # caps CONCURRENT Spark jobs — create it with 8 slots
    )
