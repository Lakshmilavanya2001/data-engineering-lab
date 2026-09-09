# Transformation & Validation Checklist

Every transformation in the pipeline, the check that proves it did what it claims, and the
number that check produced on the reference dataset (seed 42). Each row is a gate: the next
stage must not run on data that failed the previous one. Part 5b of the notebook runs the
notebook-side checks automatically and prints PASS/FAIL per row.

The principle: **a transformation without a validation is a rumour.**

## Stage 0 — Generation and placement (`phase0_setup.py`)

| # | Transformation | Validation | Expected | How to check |
|---|---|---|---|---|
| 0.1 | Generate `watch_events` + `subscribers` from ONE seed | Manifest run_id matches the config | `219e36766df2` | `phase0_setup.py --stage verify` |
| 0.2 | Write 180 daily CSV partitions to the shared volume | Count of `dt=*` folders | 180 | same |
| 0.3 | Seed `subscribers` into Postgres | Row count | 200,000 | same, or EzPresto `count(*)` |
| 0.4 | Grant SELECT to every login role | `has_table_privilege` for all roles | True | same |
| 0.5 | Label base rate | `avg(churned_next_30d)` | 0.119 | EzPresto query A2 |

**Why 0.1 matters:** the label in Postgres is causally tied to the events on the volume. Regenerate
one without the other and every downstream number still *looks* right while the model's AUC
collapses to 0.5. The manifest is the only thing that catches it.

## Stage 1 — Curate with Spark (`spark_curate_events.py`)

| # | Transformation | Validation | Expected | How to check |
|---|---|---|---|---|
| 1.1 | Read CSV with an explicit schema (no inference pass) | Input partitions == input files | 180 | driver log `input partitions` |
| 1.2 | `dropDuplicates(event_id)` | Rows out == rows in (source has no dupes) | 20,010,929 | driver log `rows written` |
| 1.3 | Drop null `subscriber_id` | Distinct subscribers seen | 200,000 | driver log `subscribers` |
| 1.4 | Keep `0 < watch_minutes <= 240` | No row outside range in output | 0 violations | notebook Part 5b |
| 1.5 | Add `is_long_view` | Column present, values in {0,1} | true | notebook Part 5b |
| 1.6 | `repartition(dt).partitionBy(dt)` → one file per day | Day folders; files per folder | 180; 1 | `ls curated/…/dt=*` |
| 1.7 | CSV → Parquet | Size ratio | 849 MB → 232 MB, **3.66×** | folder size |

**Idempotency:** `mode("overwrite")` — re-running a student's job replaces their folder rather
than appending. Run it twice; the numbers must not change.

## Stage 2 — Feature build on the GPU (notebook Parts 2–3)

| # | Transformation | Validation | Expected | How to check |
|---|---|---|---|---|
| 2.1 | Partition pruning: read only `dt >= 2026-05-31` | Folders read / folders present | 30 / 180 | Part 2 output |
| 2.2 | Column pruning: read 4 of 8 columns | `COLS` length | 4 | Part 3 code |
| 2.3 | Squash: events → one row per subscriber | Rows out; rows out < rows in | 196,564 | Part 3 output |
| 2.4 | CPU and GPU squash produce the same table | Row count and sum(minutes) equal | identical | Part 5b |
| 2.5 | Feature ranges | `completion_rate` in [0,1]; counts ≥ 0 | 0 violations | Part 5b |

**2.3 is the most important number in the lab.** 196,564 ≠ 200,000. The 3,436 missing people
watched nothing in the window. 63% of them churned (vs 11.9% overall).

## Stage 3 — Label fetch and join (notebook Parts 4–5)

| # | Transformation | Validation | Expected | How to check |
|---|---|---|---|---|
| 3.1 | Read `subscribers` from Postgres | Row count; churn rate | 200,000; 0.119 | Part 4 output |
| 3.2 | **LEFT** join subscribers ← usage | Rows out == subscribers (nothing dropped) | 200,000 | Part 5b |
| 3.3 | Fill missing activity with 0 | Nulls in feature columns after fill | 0 | Part 5b |
| 3.4 | Join key uniqueness | `subscriber_id` unique on both sides | true | Part 5b |
| 3.5 | Zero-activity group preserved | Rows with `sessions_30d == 0` | 3,436 | Part 5b |
| 3.6 | Signal sanity | mean minutes churned vs stayed | ~205 vs ~577 | Part 5 output |

**Why LEFT:** an INNER join here deletes 3,436 rows including 2,172 churners — the strongest
signal in the data — and produces no error. Row 3.2 is the only thing that catches it.

## Stage 4 — Train and register (notebook Parts 6–8)

| # | Transformation | Validation | Expected | How to check |
|---|---|---|---|---|
| 4.1 | One-hot encode `plan`, `country`, `payment_method` | Feature count | 19 (7 numeric + 12 one-hot) | Part 6 output |
| 4.2 | Stratified 75/25 split | Churn rate equal in train and test | ±0.002 | Part 5b |
| 4.3 | Train XGBoost on GPU | Held-out AUC | 0.86–0.88 | Part 6 output |
| 4.4 | Leakage check | AUC not suspiciously close to 1.0 | < 0.95 | Part 6 |
| 4.5 | Noise check | `country_*` importance spread | < 0.005 | Part 7 output |
| 4.6 | Register in MLflow | Model version created; AUC metric logged | v1 | MLflow UI |

## Stage 5 — CUDA-X acceleration (notebook Parts 9–10)

| # | Transformation | Validation | Expected | How to check |
|---|---|---|---|---|
| 5.1 | cuML RandomForest vs scikit-learn | AUC within 0.02 of each other | true | Part 9 output |
| 5.2 | cuVS nearest-neighbour vs scikit-learn brute force | Same neighbour sets (recall@10) | > 0.99 | Part 10 output |
| 5.3 | Lookalike churn score | AUC of the model-free score | 0.75–0.85 | Part 10 output |

**Rule for every speed-up you quote:** the accelerated result must be validated against the
CPU result *before* the timing is reported. A fast wrong answer is worth nothing.

## Sign-off

Data is **ready for modelling** when every row in stages 0–3 passes. Data is **ready for a
customer conversation** when stages 4–5 pass as well and the numbers have been re-measured on
the dataset in front of you — never quoted from this file.
