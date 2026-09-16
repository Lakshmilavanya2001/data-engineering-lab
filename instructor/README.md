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

### Running it anywhere else

Every path and coordinate is a flag, so nothing is tied to a PCAI shared volume:

```bash
python phase0_setup.py --stage all \
  --out-root /data \
  --pg-host <host> --pg-port 5432 --pg-db app_db --pg-user postgres \
  --seed 42 --days 180 --end-date 2026-06-29 \
  --events 20010929 --subscribers 200000
```

`--stage seed` is an alias for `--stage postgres`. `--events` is an **acceptance
target**, not an input: the count is emergent from the seeded draw, so a mismatch is
reported rather than forced. Changing `--seed`, `--days`, `--end-date` or
`--subscribers` changes the `run_id`, which is how a reduced dataset is prevented from
passing as the reference one.

A reduced dataset for rehearsals or CI takes under a second:

```bash
python phase0_setup.py --stage generate --out-root /tmp/small \
  --seed 42 --days 10 --subscribers 5000 --end-date 2026-06-29
python3 test_phase0.py --out-root /tmp/small --reduced
```

### Checking it

`test_phase0.py` runs the acceptance suite: manifest and shape, schema and
cleanliness, distributions. Against a full regeneration it is 32 of 32; the Postgres
checks are skipped rather than failed when no `--pg-host` is given.

```bash
python3 test_phase0.py --out-root <root>                       # CSV only
python3 test_phase0.py --out-root <root> --pg-host <host>      # and the database
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
| `manifest.json` | out-root | run id, counts, per-file sha256, library versions |

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
| `test_phase0.py` | Acceptance suite for a generated dataset. |
| `requirements.txt` | Runtime pins. numpy 2.4+ and pandas 3.0+; the output is identical across that range. |
| `DEVELOPER-RESPONSE.md` | Reply to the platform team's rewrite specification, and the record of what the interface contract required. |

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
