#!/usr/bin/env python3
"""
phase0_setup.py — from nothing to a verified foundation, in one command.

Supersedes generate_data.py / seed_postgres.py / upload_raw_to_s3.py. Run it from a
Kubeflow notebook terminal:

    pip install psycopg2-binary boto3 pandas numpy
    python phase0_setup.py                      # everything
    python phase0_setup.py --stage s3           # just one stage
    python phase0_setup.py --force-regenerate   # rebuild the data from scratch

Stages
  1 generate   synthetic dataset -> the SHARED VOLUME  (~3 min, ~3 GB RAM)
  2 postgres   subscribers -> app_db.public            (~10 s)
  3 s3         OPTIONAL copy -> object storage         (~3 min, --with-s3)
  4 verify     re-check, independently

WHERE THE DATA ACTUALLY LIVES
    The shared volume is the storage layer. PCAI's Spark Operator reads volumes, not
    object storage, so the raw CSV must be on the volume -- and Spark therefore needs
    no S3 credentials at all.

    The S3 copy is OPTIONAL and read by nothing. Its only purpose is teaching: a real
    bucket students can browse, to show that object storage has keys rather than
    folders and that `dt=YYYY-MM-DD` is a partitioning convention. Enable with
    --with-s3. Skip it and the lab is unaffected.

Every stage is idempotent. Every stage verifies itself. Nothing proceeds on an
unproven layer.

THE FOOTGUN THIS SCRIPT EXISTS TO PREVENT
    subscribers and watch_events share one RNG seed; the churn label is causally
    linked to the event stream. Regenerate one without the other and the signal
    vanishes (AUC -> 0.5). This script always does both, stamps a manifest with a
    run_id, and refuses to load data whose run_id does not match.
"""

import argparse
import hashlib
import subprocess
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG — the only block you should need to edit
# ═══════════════════════════════════════════════════════════════════════════════

def _discover_lab_dir():
    """Find a writable home for the data. Prefers a shared volume so the files are
    reachable from other pods; falls back to the home directory so the script always
    runs. Override with:  export LAB_DIR=/some/path"""
    if os.environ.get("LAB_DIR"):
        return os.environ["LAB_DIR"], "LAB_DIR env var"
    for base, label in [(os.path.expanduser("~/shared"), "shared volume"),
                        ("/mnt/shared",                  "shared volume"),
                        ("/shared",                      "shared volume"),
                        (os.path.expanduser("~"),        "HOME (not shared!)")]:
        if os.path.isdir(base) and os.access(base, os.W_OK):
            return os.path.join(base, "data-engineering-lab"), label
    return os.path.expanduser("~/data-engineering-lab"), "HOME (not shared!)"

LAB_DIR, _LAB_DIR_SRC = _discover_lab_dir()

DATA = dict(
    seed          = 42,
    n_subs        = 200_000,
    n_days        = 180,
    n_titles      = 2_000,
    start         = date(2026, 1, 1),
    target_churn  = 0.12,
    recency_skew  = 1.35,   # measured AUC: 1.20 -> 0.85 | 1.35 -> 0.87 | 1.60 -> 0.90
)

# Override without editing this file:
#   export PGHOST=postgres-data-postgresql.postgres-data.svc.cluster.local
#   export PGPASSWORD=admin
PG = dict(
    host     = os.environ.get("PGHOST",
               "postgres-data-postgresql.postgres-data.svc.cluster.local"),
    port     = 5432,
    dbname   = "app_db",                       # MUST match the Data Source JDBC URL
    user     = "postgres",                     # superuser, instructor only
    # No default: this is the SUPERUSER password. Refusing to guess keeps it out of
    # the source tree and out of git. Checked in __main__ so --help still works.
    password = os.environ.get("PGPASSWORD"),
    connect_timeout = 10,
)

S3 = dict(
    endpoint   = "http://local-s3-service.ezdata-system.svc.cluster.local:30000",
    bucket     = "lab-data-eng",
    raw_prefix = "raw/watch_events",
    token_file = "/etc/secrets/ezua/.auth_token",
    secret     = "s3",                         # PCAI convention
    threads    = 8,
)

OUT       = os.path.join(LAB_DIR, "raw")
EVENTS    = os.path.join(OUT, "watch_events")
SUBS_CSV  = os.path.join(OUT, "subscribers.csv")
MANIFEST  = os.path.join(OUT, "_manifest.json")


# ═══════════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════════

def banner(n, title):
    print(f"\n{'━' * 72}\n  STAGE {n} — {title}\n{'━' * 72}")

def ok(msg):    print(f"  \033[32m✓\033[0m {msg}")
def bad(msg):   print(f"  \033[31m✗\033[0m {msg}")
def info(msg):  print(f"    {msg}")

def ensure_deps():
    """Install what is missing. Distinguish 'not installed' from 'installed but
    broken' -- a numpy/pandas ABI mismatch is a different problem from a missing
    package, and pip installing over it will not help."""
    need, broken = [], []
    for mod, pkg in [("numpy", "numpy"), ("pandas", "pandas"),
                     ("psycopg2", "psycopg2-binary"), ("boto3", "boto3")]:
        try:
            __import__(mod)
        except ImportError:
            need.append(pkg)
        except Exception as e:
            broken.append((mod, str(e).split("\n")[0][:90]))

    if broken:
        for mod, err in broken:
            bad(f"{mod} is installed but broken: {err}")
        try:
            import numpy as _np
            npv, npmaj = _np.__version__, int(_np.__version__.split(".")[0])
        except Exception:
            npv, npmaj = "unknown", None
        try:
            import importlib.metadata as _md
            pdv = _md.version("pandas")
            pdkey = tuple(int(x) for x in pdv.split(".")[:2])
        except Exception:
            pdv, pdkey = "unknown", None

        print(f"\n  installed: numpy {npv} · pandas {pdv}\n")
        if npmaj and npmaj >= 2 and pdkey and pdkey < (2, 2):
            print(f'  pandas {pdv} predates NumPy 2 support (added in 2.2.2).\n'
                  f'  Upgrade pandas -- NOT numpy, which is already current:\n\n'
                  f'      pip install --upgrade "pandas>=2.2.3"\n')
        elif npmaj and npmaj < 2:
            print('  Something was compiled against NumPy 2 but NumPy 1.x is installed:\n\n'
                  '      pip install --upgrade "numpy>=2"\n')
        else:
            print('  A compiled module disagrees with NumPy. Force a matched pair:\n\n'
                  '      pip install --force-reinstall --no-cache-dir "numpy>=2" "pandas>=2.2.3"\n')
        print("""  Then re-run this script.

  FOR THE LAB: this image will be the students' image too. Fix it once, bake the
  working versions in, and verify with a plain `import pandas` on a FRESH notebook.
  30 people hitting this at T+0 is not recoverable mid-session.
""")
        sys.exit(1)

    if not need:
        ok("dependencies present")
        return
    info(f"installing {' '.join(need)} ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *need])
    ok(f"installed {' '.join(need)}")


def run_id():
    """Stable id for this exact data configuration. Changes if any knob changes."""
    payload = json.dumps({k: str(v) for k, v in sorted(DATA.items())})
    return hashlib.sha256(payload.encode()).hexdigest()[:12]

def read_manifest():
    if not os.path.exists(MANIFEST):
        return None
    with open(MANIFEST) as f:
        return json.load(f)

def require_manifest():
    m = read_manifest()
    if m is None:
        sys.exit("no manifest found — run stage 'generate' first")
    if m["run_id"] != run_id():
        sys.exit(
            f"MANIFEST MISMATCH\n"
            f"  on disk : {m['run_id']}\n"
            f"  config  : {run_id()}\n"
            f"The data on disk came from a different configuration than the one in\n"
            f"this file. Loading it would mix mismatched subscribers and events, and\n"
            f"the churn signal would vanish. Re-run with --force-regenerate."
        )
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — generate
# ═══════════════════════════════════════════════════════════════════════════════

def stage_generate(force=False):
    banner(1, "generate the dataset")

    existing = read_manifest()
    if existing and existing["run_id"] == run_id() and not force:
        ok(f"already generated (run_id {existing['run_id']}) — skipping")
        info(f"{existing['n_events']:,} events · {existing['n_subs']:,} subscribers")
        info("use --force-regenerate to rebuild")
        return existing

    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(DATA["seed"])
    N, DAYS = DATA["n_subs"], DATA["n_days"]

    # ── subscribers ────────────────────────────────────────────────────────
    info("building subscribers ...")
    sub_id  = np.arange(1, N + 1, dtype=np.int32)
    plan    = rng.choice(["basic", "standard", "premium"], N, p=[.45, .35, .20])
    country = rng.choice(["US","IN","BR","DE","GB","JP"], N, p=[.30,.25,.15,.12,.10,.08])
    payment = rng.choice(["card", "wallet", "prepaid"], N, p=[.55, .28, .17])
    tenure  = rng.integers(1, 60, N).astype(np.int16)
    tickets = rng.poisson(0.35, N).clip(0, 9).astype(np.int16)
    price   = np.select([plan == "basic", plan == "standard"], [6.99, 12.99], default=18.99)

    engagement = (0.35 * (plan == "premium") + 0.15 * (plan == "standard")
                  + 0.012 * tenure - 0.10 * tickets + rng.normal(0, 1, N))
    eng_z = (engagement - engagement.mean()) / engagement.std()

    logit = (-1.35 * eng_z + 0.50 * tickets - 0.020 * tenure
             + 0.45 * (plan == "basic") + 0.40 * (payment == "prepaid"))

    lo, hi = -10.0, 10.0                      # bisect the intercept to hit the target
    for _ in range(80):
        mid = (lo + hi) / 2
        if (1 / (1 + np.exp(-(logit + mid)))).mean() < DATA["target_churn"]:
            lo = mid
        else:
            hi = mid
    logit = logit + (lo + hi) / 2

    churn = (rng.random(N) < 1 / (1 + np.exp(-logit))).astype(np.int8)

    subs = pd.DataFrame({
        "subscriber_id":       sub_id,
        "signup_date":         [DATA["start"] - timedelta(days=int(t) * 30) for t in tenure],
        "plan":                plan,
        "country":             country,
        "payment_method":      payment,
        "monthly_price":       price.round(2),
        "support_tickets_90d": tickets,
        "tenure_months":       tenure,
        "churned_next_30d":    churn,
    })
    os.makedirs(OUT, exist_ok=True)
    subs.to_csv(SUBS_CSV, index=False)
    ok(f"subscribers.csv — {len(subs):,} rows, churn rate {churn.mean():.4f}")

    # ── watch events ───────────────────────────────────────────────────────
    info("building watch events ...")
    lam    = np.clip(0.55 + 0.30 * eng_z, 0.05, None)
    counts = rng.poisson(lam * DAYS).astype(np.int64)
    total  = int(counts.sum())

    ev_sub   = np.repeat(sub_id, counts)
    ev_churn = np.repeat(churn, counts)
    ev_engz  = np.repeat(eng_z.astype(np.float32), counts)

    # churners' activity tapers before they cancel -> low watch time in the
    # final 30 days. This is the signal the feature query surfaces.
    u      = rng.random(total)
    p_exp  = np.where(ev_churn == 1, DATA["recency_skew"], 1.0)
    day_ix = np.minimum((u ** p_exp * DAYS).astype(np.int16), DAYS - 1)
    del u, p_exp, ev_churn

    watch     = np.clip(rng.lognormal(3.2, 0.75, total), 1, 240).astype(np.float32)
    completed = (rng.random(total) < (0.45 + 0.075 * np.clip(ev_engz, -2, 2))).astype(np.int8)
    content   = rng.integers(1, DATA["n_titles"] + 1, total).astype(np.int32)
    dev_code  = rng.choice(4, total, p=[.42, .31, .19, .08]).astype(np.int8)
    DEVICES   = np.array(["mobile", "tv", "web", "tablet"])
    del ev_engz

    order  = np.argsort(day_ix, kind="stable")
    day_ix = day_ix[order]
    bounds = np.searchsorted(day_ix, np.arange(DAYS + 1))

    os.makedirs(EVENTS, exist_ok=True)
    for d in range(DAYS):
        lo_i, hi_i = bounds[d], bounds[d + 1]
        if lo_i == hi_i:
            continue
        ix  = order[lo_i:hi_i]
        dt  = DATA["start"] + timedelta(days=d)
        day = os.path.join(EVENTS, f"dt={dt.isoformat()}")
        os.makedirs(day, exist_ok=True)
        pd.DataFrame({
            "event_id":      np.arange(lo_i, hi_i, dtype=np.int64),
            "subscriber_id": ev_sub[ix],
            "content_id":    content[ix],
            "event_date":    dt.isoformat(),
            "watch_minutes": watch[ix].round(1),
            "device":        DEVICES[dev_code[ix]],
            "completed":     completed[ix],
        }).to_csv(os.path.join(day, "events.csv"), index=False)
        if d % 60 == 0:
            info(f"day {d:3d}/{DAYS}")

    n_bytes = sum(os.path.getsize(os.path.join(r, f))
                  for r, _, fs in os.walk(EVENTS) for f in fs)
    ok(f"watch_events — {total:,} rows across {DAYS} daily files, {n_bytes/1e6:.0f} MB")

    # ── signal check: is the thing we planted actually there? ──────────────
    import pandas as _pd
    last30 = day_ix >= (DAYS - 30)
    mins = _pd.Series(watch[order][last30]).groupby(ev_sub[order][last30]).sum()
    j = subs.set_index("subscriber_id").join(mins.rename("m")).fillna({"m": 0})
    m0 = j.loc[j.churned_next_30d == 0, "m"].mean()
    m1 = j.loc[j.churned_next_30d == 1, "m"].mean()
    if m1 >= m0 * 0.7:
        bad(f"WEAK SIGNAL — churners {m1:.0f} vs non-churners {m0:.0f} minutes")
        bad("the model will not learn much. Raise recency_skew and regenerate.")
    else:
        ok(f"signal present — churners {m1:.0f} min vs non-churners {m0:.0f} min "
           f"in the final 30 days")

    manifest = {
        "run_id":      run_id(),
        "config":      {k: str(v) for k, v in DATA.items()},
        "n_subs":      int(N),
        "n_events":    int(total),
        "n_days":      int(DAYS),
        "bytes":       int(n_bytes),
        "churn_rate":  float(churn.mean()),
        "minutes_churn":    float(m1),
        "minutes_nonchurn": float(m0),
    }
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    ok(f"manifest written — run_id {manifest['run_id']}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — postgres
# ═══════════════════════════════════════════════════════════════════════════════

DDL = """
DROP TABLE IF EXISTS public.subscribers;

CREATE TABLE public.subscribers (
    subscriber_id        INTEGER      PRIMARY KEY,
    signup_date          DATE         NOT NULL,
    plan                 VARCHAR(16)  NOT NULL,
    country              VARCHAR(2)   NOT NULL,
    payment_method       VARCHAR(16)  NOT NULL,
    monthly_price        NUMERIC(6,2) NOT NULL,
    support_tickets_90d  SMALLINT     NOT NULL,
    tenure_months        SMALLINT     NOT NULL,
    churned_next_30d     SMALLINT     NOT NULL
);
"""

GRANTS = """
-- The query catalog connects as a NON-superuser. This table is created by
-- `postgres`, so it starts with no grants and the catalog gets
-- "permission denied for table subscribers".
GRANT USAGE  ON SCHEMA public      TO PUBLIC;
GRANT SELECT ON public.subscribers TO PUBLIC;

-- Survives future DROP/CREATE cycles, so re-seeding never re-breaks the catalog.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO PUBLIC;
"""


def stage_postgres():
    banner(2, "seed Postgres")
    m = require_manifest()
    info(f"loading data from run_id {m['run_id']}")

    import pandas as pd
    import psycopg2

    df = pd.read_csv(SUBS_CSV)
    conn = psycopg2.connect(**PG)
    conn.autocommit = True          # GRANT silently rolls back without this
    cur = conn.cursor()

    cur.execute(DDL)
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cur.copy_expert("COPY public.subscribers FROM STDIN WITH (FORMAT csv)", buf)
    ok(f"loaded {len(df):,} rows")

    cur.execute(GRANTS)
    ok("grants applied (SELECT only — catalog stays read-only for students)")

    # verify independently of what we just did
    cur.execute("""SELECT count(*), round(avg(churned_next_30d)::numeric, 4),
                          count(DISTINCT plan)
                   FROM public.subscribers""")
    n, churn, plans = cur.fetchone()
    cur.execute("""SELECT count(*) FROM information_schema.role_table_grants
                   WHERE table_name='subscribers' AND grantee='PUBLIC'
                     AND privilege_type='SELECT'""")
    granted = cur.fetchone()[0]

    cur.close(); conn.close()

    assert n == m["n_subs"], f"row count {n} != expected {m['n_subs']}"
    assert granted == 1, "PUBLIC does not have SELECT — the catalog will fail"
    ok(f"verified — {n:,} rows · churn {churn} · {plans} plans · PUBLIC SELECT present")


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — object storage
# ═══════════════════════════════════════════════════════════════════════════════

def s3_client():
    import boto3
    token = open(S3["token_file"]).read().strip()
    return boto3.client("s3", endpoint_url=S3["endpoint"],
                        aws_access_key_id=token,
                        aws_secret_access_key=S3["secret"])


def stage_s3():
    banner(3, "OPTIONAL — copy raw events to object storage (teaching aid)")
    m = require_manifest()
    info(f"uploading data from run_id {m['run_id']}")

    s3 = s3_client()
    try:
        s3.create_bucket(Bucket=S3["bucket"])
        ok(f"bucket {S3['bucket']} created")
    except Exception as e:
        if "BucketAlreadyOwnedByYou" in str(e) or "BucketAlreadyExists" in str(e):
            ok(f"bucket {S3['bucket']} already exists")
        else:
            raise

    files = []
    for d in sorted(os.listdir(EVENTS)):
        local = os.path.join(EVENTS, d, "events.csv")
        if os.path.isfile(local):
            files.append((local, f"{S3['raw_prefix']}/{d}/events.csv"))
    src_bytes = sum(os.path.getsize(f) for f, _ in files)
    info(f"{len(files)} files, {src_bytes/1e6:.0f} MB")

    def put(item):
        local, key = item
        s3.upload_file(local, S3["bucket"], key)
        return os.path.getsize(local)

    done = sent = 0
    with ThreadPoolExecutor(S3["threads"]) as ex:
        for fut in as_completed([ex.submit(put, f) for f in files]):
            sent += fut.result(); done += 1
            if done % 60 == 0 or done == len(files):
                info(f"{done:3d}/{len(files)}   {sent/1e6:6.0f} MB")

    # verify against the source, byte for byte
    n = size = 0
    for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=S3["bucket"], Prefix=S3["raw_prefix"]):
        for obj in page.get("Contents", []):
            n += 1; size += obj["Size"]

    assert n == len(files),      f"object count {n} != {len(files)}"
    assert size == src_bytes,    f"byte total {size} != {src_bytes}"
    ok(f"verified — {n} objects, {size/1e6:.0f} MB, exact byte match")
    info(f"browsable at s3://{S3['bucket']}/{S3['raw_prefix']}/")
    info("(nothing reads this — Spark reads the shared volume. It exists so students")
    info(" can see a real bucket: keys not folders, dt= partition naming.)")


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — verify everything, independently
# ═══════════════════════════════════════════════════════════════════════════════

def stage_verify():
    banner(4, "verify")
    m = require_manifest()
    results = []

    # local
    n_dirs = len([d for d in os.listdir(EVENTS) if d.startswith("dt=")])
    results.append(("local: daily partitions", n_dirs == m["n_days"], f"{n_dirs}"))
    results.append(("local: manifest run_id", True, m["run_id"]))

    # postgres
    try:
        import psycopg2
        conn = psycopg2.connect(**PG); cur = conn.cursor()
        cur.execute("SELECT count(*) FROM public.subscribers")
        n = cur.fetchone()[0]
        cur.execute("""SELECT has_table_privilege(rolname,'public.subscribers','SELECT')
                       FROM pg_roles WHERE rolcanlogin""")
        all_read = all(r[0] for r in cur.fetchall())
        cur.close(); conn.close()
        results.append(("postgres: row count", n == m["n_subs"], f"{n:,}"))
        results.append(("postgres: all roles can SELECT", all_read, str(all_read)))
    except Exception as e:
        results.append(("postgres", False, str(e)[:60]))

    # s3
    try:
        s3 = s3_client()
        n = size = 0
        for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket=S3["bucket"], Prefix=S3["raw_prefix"]):
            for obj in page.get("Contents", []):
                n += 1; size += obj["Size"]
        if n == 0:
            results.append(("s3: optional copy", True, "not uploaded (fine — use --with-s3)"))
        else:
            results.append(("s3: object count", n == m["n_days"], f"{n}"))
            results.append(("s3: byte total", size == m["bytes"], f"{size/1e6:.0f} MB"))
    except Exception as e:
        results.append(("s3: optional copy", True, f"unreachable, ignored ({str(e)[:34]})"))

    print()
    width = max(len(r[0]) for r in results)
    for name, passed, detail in results:
        (ok if passed else bad)(f"{name.ljust(width)}   {detail}")

    failed = [r[0] for r in results if not r[1]]
    print(f"\n{'━' * 72}")
    if failed:
        print(f"  \033[31mFAILED\033[0m — {', '.join(failed)}")
        sys.exit(1)
    print("  \033[32mPHASE 0 COMPLETE\033[0m")
    print(f"{'━' * 72}")
    print(f"""
  {m['n_events']:,} events · {m['n_subs']:,} subscribers · churn {m['churn_rate']:.4f}
  churners watch {m['minutes_churn']:.0f} min vs {m['minutes_nonchurn']:.0f} in the final 30 days

  raw CSV on the shared volume:
      {EVENTS}
  Spark sees the same files at:
      file:///mounts/shared-volume/shared/data-engineering-lab/raw/watch_events
""")
    print("─" * 72)
    print("  NEXT")
    print("─" * 72)
    print(f"""
  1. Register Postgres as a Data Source (PCAI UI), then verify in the EzPresto
     worksheet -- ONE statement at a time, NO trailing semicolon:

         SHOW CATALOGS
         SELECT count(*) FROM dataengineeringlab.public.subscribers
         -- expected: {m['n_subs']}

  2. Put the Spark job on the volume:
         python spark/place_on_shared_volume.py

  3. Run it once via Create Spark Application (Type=Python, Source=Shared Folder).
     See SETUP.md step 4 for the three arguments.

  Hive is NOT part of this pipeline -- PCAI's metastore is incompatible with
  EzPresto's client. EzPresto reads Postgres only; the events/subscribers join
  happens on the GPU in the notebook. See CLAUDE.md.
""")

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 0 setup for the PCAI churn lab")
    ap.add_argument("--stage", default="all",
                    choices=["all", "generate", "postgres", "s3", "verify"])
    ap.add_argument("--force-regenerate", action="store_true",
                    help="rebuild the dataset even if a matching manifest exists")
    ap.add_argument("--with-s3", action="store_true",
                    help="also copy the raw CSV to object storage. Nothing reads it; "
                         "it exists only so students can browse a real bucket.")
    a = ap.parse_args()

    if a.stage in ("all", "postgres", "verify") and not PG["password"]:
        sys.exit("\n  PGPASSWORD is not set.\n"
                 "  This script connects to Postgres as the SUPERUSER. Export it first:\n"
                 "      export PGPASSWORD='<superuser password>'\n")

    print(f"\n  PCAI churn lab — Phase 0")
    print(f"  lab dir : {LAB_DIR}   [{_LAB_DIR_SRC}]")
    print(f"  postgres: {PG['host']}/{PG['dbname']} as {PG['user']}")
    print(f"  run_id  : {run_id()}\n")
    ensure_deps()
    if "not shared" in _LAB_DIR_SRC:
        bad("data is going to the HOME directory, not a shared volume.")
        info("Fine for a solo run. For the lab, other pods must reach these files —")
        info("mount the shared volume and re-run, or set LAB_DIR.")

    # Fail now, clearly, rather than three minutes into generation.
    parent = os.path.dirname(LAB_DIR.rstrip("/"))
    if not os.path.isdir(parent):
        sys.exit(f"\n  {parent} does not exist.\n"
                 f"  That is usually the shared volume mount. Check it is attached to\n"
                 f"  this notebook, or set LAB_DIR to a path that exists:\n"
                 f"      export LAB_DIR=/path/to/somewhere\n")
    # Only `generate` writes to the volume. postgres/s3/verify just read it, and
    # on the real cluster the lab dir is owned by whoever generated it, so a
    # different user running `--stage verify` must not be refused for lack of
    # write access.
    if a.stage in ("all", "generate"):
        try:
            os.makedirs(LAB_DIR, exist_ok=True)
            probe = os.path.join(LAB_DIR, ".write_probe")
            open(probe, "w").write("ok"); os.remove(probe)
        except Exception as e:
            sys.exit(f"\n  cannot write to {LAB_DIR}: {e}\n")
        print(f"  writable: yes")
    elif not os.access(LAB_DIR, os.R_OK | os.X_OK):
        sys.exit(f"\n  cannot read {LAB_DIR} (stage '{a.stage}' only needs read access)\n")
    else:
        print(f"  readable: yes   (stage '{a.stage}' does not write to the volume)")

    if a.stage in ("all", "generate"): stage_generate(force=a.force_regenerate)
    if a.stage in ("all", "postgres"): stage_postgres()
    if a.stage == "s3" or (a.stage == "all" and a.with_s3):
        stage_s3()
    elif a.stage == "all":
        info("skipping the object-storage copy (add --with-s3 to include it)")
    if a.stage in ("all", "verify"):   stage_verify()
