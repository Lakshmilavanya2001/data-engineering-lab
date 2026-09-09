# Lab 18 — Data Engineering Pipeline (Airflow · Spark · EzPresto · CUDA-X · MLflow)

*Curriculum slot: 3.1 Feature Engineering & ETL/DataOps — "Data Pipeline with Airflow, Spark and EzPresto".*

**Duration** ~3 h · **GPU required** Yes (1 slice per participant) · **Backend** HPE PCAI
**Status** 🚧 In build — proven end to end for a single participant

## What this lab does
Takes **20 million raw event rows** sitting in object storage and turns them into a
**200,000-row training table**, trains a churn model on the GPU, versions it in MLflow, and
deploys it. One tool per concept, each appearing at the moment it becomes necessary.

The business question: *will this subscriber cancel in the next 30 days?*

## The shape of the problem
A model needs **one row per person, with the answer attached**. What exists instead is:

| | rows | where | has the label? |
|---|---|---|---|
| `watch_events` | 20,010,929 | object storage / shared volume | no |
| `subscribers` | 200,000 | Postgres | **yes** |

Neither table can train anything alone. The entire data-engineering task is to squash
20M event rows into 200k people rows and attach the answer from the other system.

## Pipeline
```
raw CSV (180 daily files, 849 MB)
   │  SPARK — read · clean · convert            [distributed compute, columnar formats]
   ▼
curated Parquet (232 MB, 3.66x smaller)
   │  cuDF — aggregate 20M -> 200k              [RAPIDS, the GPU doing real work]
   │  EzPresto — read subscribers from Postgres [federation]
   │  cuDF — join on the GPU
   ▼
training table (200k x 12)
   │  XGBoost on GPU -> AUC 0.868
   ▼
MLflow registry -> MLIS endpoint

AIRFLOW runs the Spark step, parameterised per participant.
```

## Outcomes (what a participant leaves with)
1. **A working pipeline flow** — raw events + a live database → validated training table →
   registered model, run end to end under their own student number.
2. **A transformation & validation checklist** — `TRANSFORMATION_VALIDATION_CHECKLIST.md`,
   executed live by notebook Part 5b (every row prints PASS/FAIL).
3. **A customer-facing data-readiness explanation** — `DATA_READINESS.md`, a one-page template
   filled with the participant's own numbers.
4. **A presales value statement** — `PRESALES_VALUE_STATEMENT.md`: the participant explains the
   value of RAPIDS/cuDF, cuML and cuVS acceleration from numbers they *measured* (notebook
   Parts 3, 9, 10, collected in Part 11) and writes three result → meaning → value statements.

## Objectives
- Explain what an orchestrator does, and why it never touches the data itself.
- See parallelism as a number: 180 files → 180 Spark tasks.
- Understand columnar storage — measured 3.66x smaller, and only reads the columns asked for.
- Understand federation: query a live database without copying it.
- Run the same aggregation on CPU and GPU with identical code.
- Read a model registry: parameters, metrics, versions, promotion.
- Measure CUDA-X acceleration honestly: accuracy checked first, then the clock, against a named
  CPU core count — and know when an approximate index is the *wrong* tool.
- Turn a measured result into a sentence a customer acts on, and know what not to say.

## Concepts (the actual syllabus)
Fact vs dimension tables · orchestration & DAGs · idempotency · parameterised runs ·
lazy evaluation · partitions & parallelism · shuffle · columnar storage · partition pruning ·
aggregation & feature engineering · federation · labels & supervised learning ·
hardware acceleration · reproducibility & registry · promotion gates

## What participants actually do

| Step | Where | Time |
|---|---|---|
| 1. Look at the raw data — 180 files, why it isn't trainable | terminal / notebook | ~10 min |
| 2. Query `subscribers` through EzPresto — no copy made | EzPresto worksheet | ~10 min |
| 3. **Run the Spark job through Airflow** — trigger `churn_pipeline` with your number | Airflow UI | ~10 min |
| 4. **`notebooks/Lab18_Train_Churn_Model.ipynb`** Parts 1–8 — cuDF squash, GPU join, **validation checklist (5b)**, train, MLflow | GPU notebook | ~40 min |
| 5. Compare AUCs | MLflow | ~5 min |
| 6. Notebook Parts 9–11 — cuML vs scikit-learn, cuVS look-alike search, your measured-results table | GPU notebook | ~20 min |
| 7. Write three value statements and fill `DATA_READINESS.md` | pairs | ~20 min |

**Airflow is live (proven 2026-09-07 on pcai1dev, student-02, 2m30s trigger to success).**
If the DAG misbehaves on the day, the Create Spark Application wizard below produces the
identical output and is the fallback — the notebook does not care which path made the
curated folder.

### Running the Spark job through Airflow (step 3, primary)
**Data Engineering → Airflow → `churn_pipeline`**

1. Make sure the DAG's toggle (left of its name) is **on** — a paused DAG queues the trigger
   and never runs it. This was the cause of the failed first trigger in August.
2. Click ▶ under Actions. Airflow ≥ 2.9 opens a **trigger form** because the DAG declares a
   `student_id` param (without params the play button would run the DAG immediately with no
   form — that is why the param exists). Enter the student number unpadded (`7`, not `"07"`)
   in the **Student number** field → Trigger. Leaving it empty fails fast and harmlessly with
   *"No student_id supplied"*; just trigger again. A JSON conf `{"student_id": 7}` via the
   REST API or CLI still works — Airflow merges it into params.
3. Open the DAG → **Grid** → click the `curate` square in the newest column → **Logs**. The
   log shows the SparkApplication being submitted, its state changing every ~10 s, and ends
   with the driver log's own summary (`rows written : 20,010,929 … day partitions : 180`).
4. The application also appears under Data Engineering → Spark Applications as
   `curate-student-NN`, same as a wizard submission.

Thirty triggers produce thirty columns in the Grid view — that picture *is* the orchestration
lesson.

### Running the Spark job (step 3)
**Data Engineering → Spark Applications → Create Spark Application**

| Screen | Setting |
|---|---|
| Details | Name `curate-student-NN` |
| Configure | Type **Python** · Source **Shared Folder** · Class Name *empty* |
| File Name | **Browse** to `data-engineering-lab/spark/curate_events.py` |
| Arguments | `NN` |
| | `file:///mounts/shared-volume/shared/data-engineering-lab/raw/watch_events` |
| | `file:///mounts/shared-volume/shared/data-engineering-lab/curated/student-NN/watch_events` |
| Driver | 1 core, 4G · Executor 1 × 1 core, 4G |

> The app file comes out as `local://`, the data arguments are `file://`. Browse fills the
> first one in for you. Substitute your own zero-padded number for `NN`.

### The notebook (step 4)
`notebooks/Lab18_Train_Churn_Model.ipynb` — 8 parts, fully documented, run top to bottom.
The only thing a participant edits is `STUDENT_ID` in Part 1.2.

**Part 1.1 checks the environment and only fixes it if broken.** On a properly built image
it prints `environment ready` and moves on — no install, no restart.

If it does have to install, it says so and **tells the participant to restart the kernel**.
That restart is unavoidable: NumPy is compiled into other packages, so replacing it under a
running kernel produces the `numpy.dtype size changed` error.

Two traps it works around, both found on real PCAI images:

- **`scikit-learn 1.3` and `scipy 1.11` predate NumPy 2 and actively pin NumPy below 2.**
  They must be *upgraded* (`scikit-learn>=1.5`, `scipy>=1.13`), not merely installed, or
  they drag NumPy back down every time.
- **mlflow requires `pandas<3`; cuDF 26.08 requires `pandas>=3`.** Given both at once, pip
  backtracks through mlflow releases to 1.27.0 (2022), whose metadata is malformed, fails,
  and leaves the environment worse. So packages are installed first and the NumPy/pandas
  pair corrected afterwards. mlflow prints a version warning and works correctly.

**Until the image is baked**, run `setup_notebook_env.sh` once from a JupyterLab terminal
(`bash ~/pcai-dataeng-lab/setup_notebook_env.sh`, 5-10 min, then restart the kernel). It installs
in the proven order and is a no-op when the environment is already complete.

**The real fix is to bake the image**, so 1.1 is always a no-op:

```
cudf-cu12 26.08 · rmm-cu12 26.08 · cuml-cu12 26.08 · cuvs-cu12 26.08 · numpy 2.4.6 · pandas 3.0.3
scikit-learn>=1.5 · scipy>=1.13 · xgboost · psycopg2-binary · mlflow>=2.9,<3
```
(cupy arrives as a dependency of cuML/cuVS. Verified together 2026-09-08: cudf 26.08.01,
cuml 26.08.00, cuvs 26.08.01, numpy 2.4.6, pandas 3.0.3, scikit-learn 1.9.0.)

**`mlflow` must be pinned below 3.** PCAI runs an MLflow **2.x server**. A 3.x client calls
`/api/2.0/mlflow/logged-models`, which that server does not implement — the run, params and
metrics all log successfully and then model *registration* fails with a 404. Symptom to
recognise: `artifact_path is deprecated, use name instead` followed by a 404.

Thirty participants each running a dependency resolver against a slightly different starting
state is thirty chances to land somewhere new.

**cuDF is deliberately not installed by the notebook.** It is a 1–2 GB download and requires
a *kernel restart*, which would break "run every cell from the top" for 30 people at once.
Bake RAPIDS into the notebook image instead — proven working set:

```
cudf-cu12 26.08 · rmm-cu12 26.08 · cuml-cu12 26.08 · cuvs-cu12 26.08 · numpy 2.4.6 · pandas 3.0.3
xgboost · scikit-learn · psycopg2-binary · mlflow
```

Without it the notebook falls back to the CPU and everything still runs; you only lose the
timed CPU-vs-GPU comparisons in Parts 3, 9 and 10. Part 1.1 reports cuDF/cuML/cuVS presence
and never installs them.

Covers: Parquet and columnar storage · partition pruning · **cuDF / RAPIDS with a timed
CPU-vs-GPU comparison** · joining across two systems · **executable validation checklist** ·
XGBoost on GPU · feature importance (including a planted noise column) · MLflow registration ·
**cuML RandomForest vs scikit-learn (accuracy checked, then timed)** · **cuVS look-alike search
vs scikit-learn brute force (recall checked, then timed)** · a measured-results table for the
value-statement exercise.

### CUDA-X parts — what was measured (2026-09-08, seed 42, 4 CPU cores vs one H200)
| Part | Workload | CPU | GPU | Check |
|---|---|---|---|---|
| 9 | RandomForest 200 trees, 150k × 19 | ~2.5–10 s (core-count dependent) | ~2 s | AUC gap 0.0006 |
| 10 | kNN, 50k queries × 150k vectors × 19 dims | 1.8 s | 0.05 s (~37×) | recall@10 0.9997 |
| 10 | look-alike churn score (no model) | AUC 0.814 | same | vs XGBoost 0.870 |

Two things to say out loud: the speed-up depends on how many CPU cores the notebook has (the
cell prints it), and cuVS's approximate index CAGRA was tried and is *worse* here (34 s,
recall 0.76) — it exists for embedding-sized vectors, not 19 dimensions. "Measured, not
quoted" is the lesson.

**cuVS footgun (hit during the build):** a `brute_force` index *references* the GPU array it
was built on without copying it. Let that array go out of scope before searching and the
search reads freed memory — recall silently drops to ~0. Keep the array in a variable.

## The DAG
`dags/churn_pipeline_dag.py` — **one** DAG, triggered once per participant:

> Airflow UI → `churn_pipeline` → ▶ → trigger form → Student number `7` → Trigger

Every path and object name derives from that number, so 30 people produce 30 independent
runs of the same DAG. Nobody edits a file.

It submits a `SparkApplication` and polls it to completion, tailing the driver log into the
Airflow task log. Three details in the spec are platform-specific and easy to get wrong:

- the API group is `sparkoperator.hpe.com/v1beta2`, **not** `sparkoperator.k8s.io`
- three PVCs must be mounted (user, shared, spark-history event log)
- the MapR `sparkConf` keys and the `imagepull` secret are required

### Platform requirement: `access_control`
PCAI refuses to load a DAG that does not declare who may use it — the scheduler reports
*"Unprotected DAG Detected"*. The DAG sets:

```python
access_control = {
    "Admin": {"can_read", "can_edit", "can_delete"},
    "All":   {"can_read", "can_edit"},
}
```

**Triggering a DAG requires `can_edit`**, not just `can_read`, so participants need both or
the Trigger button silently does nothing for them. They do not get `can_delete` — 30 people
should be able to run this DAG, not remove it.

### Before it will run
1. **Airflow pool** — Admin → Pools → `spark_pool`, **8** slots. Caps concurrent Spark jobs
   while `max_active_runs=40` still lets every participant see their run start.
2. **RBAC — NOT needed on PCAI.** PCAI launches the task pod inside the triggering user's own
   namespace (`dag_deployed_in_user_ns` in the event log) with an identity that can already
   create SparkApplications there. `dags/rbac_airflow_spark.yaml` is kept only for a plain
   Airflow install where the task pod lacks that right.
3. **CONFIG block** — namespace, image, service account and `SPARK_USER` at the top of the
   DAG are cluster-specific. The defaults match pcai1dev. On another cluster override them
   without editing the file: Airflow → Admin → Variables → `lab18_namespace`,
   `lab18_spark_image`, `lab18_service_account`, `lab18_spark_user`. Take the values from a
   `SparkApplication` that has actually completed (Spark Applications → app → YAML view).
4. **The DAG must be unpaused** and participants need `can_edit` (see `access_control`).

## Measured, not assumed
| Figure | Value |
|---|---|
| Events | 20,010,929 |
| Subscribers | 200,000 |
| Raw CSV | 849 MB, 180 files |
| Curated Parquet | 232 MB — **3.66x** compression |
| Churn rate | 0.119 |
| Test AUC | 0.868 |
| Spark job wall-clock | ~1 min 50 s |

Every number here is a measurement. Re-measure before re-quoting if the dataset changes.
