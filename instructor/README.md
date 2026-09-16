# Instructor setup — generating and seeding the lab data

Everything in this folder is **instructor-only**. It connects to Postgres as the
**superuser** and writes the shared, read-only copy of the lab data. Participants never
run it and never need it.

Run it **once per cluster**, before the session, from a terminal in any notebook server
that has the shared volume mounted.

## One command

```bash
export PGPASSWORD='<postgres superuser password>'
python phase0_setup.py
```

Roughly four minutes. It runs four stages and verifies itself after each one:

| Stage | What it does |
|---|---|
| `generate` | Builds the synthetic dataset onto the shared volume (~3 min, ~3 GB RAM) |
| `postgres` | Loads `subscribers` into `app_db.public` with durable grants (~10 s) |
| `s3` | **Optional** copy of the raw CSV to object storage — add `--with-s3` |
| `verify` | Re-checks every layer independently |

Useful variants:

```bash
python phase0_setup.py --stage verify      # check an existing setup, read-only
python phase0_setup.py --with-s3           # also populate the browsable bucket
python phase0_setup.py --force-regenerate  # rebuild the dataset from scratch
```

`--stage verify` needs no write access, so anyone can use it to confirm the foundation.
A healthy run prints five ticks:

```
✓ local: daily partitions          180
✓ local: manifest run_id           219e36766df2
✓ postgres: row count              200,000
✓ postgres: all roles can SELECT   True
✓ s3: optional copy                not uploaded (fine — use --with-s3)
```

## What it produces

| Artifact | Where | Size |
|---|---|---|
| `raw/watch_events/dt=YYYY-MM-DD/events.csv` | shared volume | 180 files, 849 MB, 20,010,929 rows |
| `subscribers` | Postgres `app_db.public` | 200,000 rows, churn rate 0.119 |
| `_manifest.json` | shared volume | stamps the run id both halves share |

The S3 copy is read by nothing. It exists only so participants can browse a real bucket
and see that object storage has keys rather than folders. Skip it and the lab is unaffected.

## The one footgun

`subscribers` and `watch_events` are generated from a **single RNG seed**, and the churn
label is causally linked to the viewing behaviour. Regenerate one without the other and
every downstream number still looks plausible while the model's AUC collapses to 0.5.

`phase0_setup.py` always does both, stamps a manifest with a run id, and refuses to load
data whose run id does not match. Use it rather than calling `generate_data.py` directly.

## Files

| File | Purpose |
|---|---|
| `phase0_setup.py` | The one command above. Generate, seed, optional S3 copy, verify. |
| `generate_data.py` | The standalone generator, kept as a readable reference for how the dataset and its label are constructed. `phase0_setup.py` contains the same logic. |

Two older scripts, `seed_postgres.py` and `upload_raw_to_s3.py`, are superseded by
`phase0_setup.py` and are deliberately **not** included — they carry a stale namespace and
would seed a database the EzPresto catalog cannot see.

## Credentials

`phase0_setup.py` reads the superuser password from `PGPASSWORD` and exits if it is unset.
No password is stored in this repository. Override the rest without editing any file:

```bash
export PGHOST=postgres-data-postgresql.postgres-data.svc.cluster.local
export LAB_DIR=/path/to/shared/data-engineering-lab
```
