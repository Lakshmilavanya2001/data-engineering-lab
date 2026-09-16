#!/usr/bin/env python3
"""
test_phase0.py — acceptance tests for the Lab 18 dataset generator.

Implements groups A (manifest/shape), B (schema and cleanliness) and C
(distributions) from DEVELOPER-MISSING-FILES. Group D is the end-to-end lab run
and cannot be automated here.

    python3 test_phase0.py --out-root /data                    # checks the CSV only
    python3 test_phase0.py --out-root /data --pg-host ... --pg-db ...   # + Postgres

Postgres checks are skipped, not failed, when no --pg-host is given, so this runs
in CI against a reduced dataset with no database:

    python3 phase0_setup.py --stage generate --out-root /tmp/small \
        --seed 42 --days 10 --subscribers 5000 --end-date 2026-06-29
    python3 test_phase0.py --out-root /tmp/small --reduced

Exit code 0 only if every executed check passes.
"""
import argparse, glob, json, os, sys
from datetime import date

ap = argparse.ArgumentParser()
ap.add_argument("--out-root", required=True)
ap.add_argument("--pg-host"); ap.add_argument("--pg-port", type=int, default=5432)
ap.add_argument("--pg-db", default="app_db"); ap.add_argument("--pg-user", default="postgres")
ap.add_argument("--reduced", action="store_true",
                help="dataset is not the reference size; skip the absolute-count checks")
A = ap.parse_args()

import numpy as np, pandas as pd

ROOT = os.path.abspath(A.out_root)
EVENTS = os.path.join(ROOT, "raw", "watch_events")
results = []
def check(name, passed, detail=""):
    results.append((name, bool(passed), detail))
    print(("  PASS  " if passed else "  FAIL  ") + name.ljust(46) + "  " + str(detail))
def skip(name, why):
    print("  SKIP  " + name.ljust(46) + "  " + why)

man_path = os.path.join(ROOT, "manifest.json")
if not os.path.exists(man_path):
    man_path = os.path.join(ROOT, "raw", "_manifest.json")
man = json.load(open(man_path))
REF = not A.reduced

print("\nA. manifest and shape")
if REF:
    check("A1 run_id is the reference value", man["run_id"] == "219e36766df2", man["run_id"])
else:
    skip("A1 run_id is the reference value", "reduced run")
dirs = sorted(glob.glob(os.path.join(EVENTS, "dt=*")))
check("A2 one directory per day", len(dirs) == man["n_days"], f"{len(dirs)}")
check("A2 one events.csv per directory",
      all(os.path.isfile(os.path.join(d, "events.csv")) for d in dirs), "")
if REF:
    check("A2 reference day count", len(dirs) == 180, f"{len(dirs)}")
    cutoff = date(2026, 5, 31)
    keep = [d for d in dirs if date.fromisoformat(os.path.basename(d)[3:]) >= cutoff]
    check("A2 30 directories at/after the cutoff", len(keep) == 30, f"{len(keep)}")

print("\nB. schema and cleanliness")
COLS = ["event_id","subscriber_id","content_id","event_date","watch_minutes","device","completed"]
total = 0; ids = []; bad_date = 0; bad_min = 0; nulls = 0; bad_done = 0; subs_seen = set()
first = True
for d in dirs:
    df = pd.read_csv(os.path.join(d, "events.csv"))
    if first:
        check("B-schema columns, in order", list(df.columns) == COLS, ",".join(df.columns))
        first = False
    dt = os.path.basename(d)[3:]
    total += len(df)
    ids.append(df.event_id.to_numpy())
    nulls += int(df.subscriber_id.isna().sum())
    bad_min += int(((df.watch_minutes <= 0) | (df.watch_minutes > 240)).sum())
    bad_date += int((df.event_date.astype(str) != dt).sum())
    bad_done += int((~df.completed.isin([0, 1])).sum())
    subs_seen.update(df.subscriber_id.unique().tolist())
allids = np.concatenate(ids)
check("B6 total rows match the manifest", total == man["n_events"], f"{total:,}")
if REF:
    check("B6 reference row count", total == 20010929, f"{total:,}")
check("B7 event_id globally unique", len(np.unique(allids)) == total,
      f"{total - len(np.unique(allids))} duplicates")
check("B8 no null subscriber_id", nulls == 0, f"{nulls}")
check("B8 watch_minutes in (0, 240]", bad_min == 0, f"{bad_min} violations")
check("B9 event_date equals its dt directory", bad_date == 0, f"{bad_date} mismatches")
check("B9 completed in {0,1}", bad_done == 0, f"{bad_done} violations")

subs_csv = os.path.join(ROOT, "raw", "subscribers.csv")
if os.path.exists(subs_csv):
    subs = pd.read_csv(subs_csv)
    check("B10 referential integrity (events -> subscribers)",
          subs_seen <= set(subs.subscriber_id.tolist()),
          f"{len(subs_seen):,} distinct ids in events")
    check("B-subs row count matches the manifest", len(subs) == man["n_subs"], f"{len(subs):,}")
else:
    skip("B10 referential integrity", "subscribers.csv not on disk")

print("\nC. distributions")
if A.pg_host:
    import psycopg2
    conn = psycopg2.connect(host=A.pg_host, port=A.pg_port, dbname=A.pg_db,
                            user=A.pg_user, password=os.environ["PGPASSWORD"])
    subs = pd.read_sql("SELECT * FROM public.subscribers", conn); conn.close()
    source = "postgres"
elif os.path.exists(subs_csv):
    source = "subscribers.csv"
else:
    subs = None; source = None

if subs is None:
    skip("C11/C12 distributions", "no subscribers source")
else:
    print(f"  (source: {source})")
    n = len(subs)
    rate = subs.churned_next_30d.mean()
    # Tolerances scale with sample size: a reduced CI dataset is legitimately
    # noisier, and a test that fails on valid data is a broken test.
    sigma = float(np.sqrt(0.119 * 0.881 / n))
    check("A5 base churn rate 0.119", abs(rate - 0.119) < max(0.002, 4 * sigma),
          f"{rate:.4f}  (n={n:,}, tol {max(0.002, 4 * sigma):.4f})")

    def spread(col):
        g = subs.groupby(col).churned_next_30d.mean()
        return float(g.max() - g.min())
    s_country, s_plan = spread("country"), spread("plan")
    # Expected max-min range of k independent proportions under the null, for a
    # column that carries no signal. country has 6 categories.
    noise_band = 4 * float(np.sqrt(0.119 * 0.881 / (n / 6)))
    if REF:
        check("C12 country spread ~0.0049", abs(s_country - 0.0049) < 0.0015, f"{s_country:.4f}")
        check("C12 plan spread ~0.0715", abs(s_plan - 0.0715) < 0.005, f"{s_plan:.4f}")
        check("C12 country spread >= 10x smaller than plan", s_plan > 10 * s_country,
              f"{s_plan / max(s_country, 1e-9):.1f}x")
    else:
        check("C12 country spread is consistent with noise", s_country < noise_band,
              f"{s_country:.4f} < {noise_band:.4f}")
        check("C12 plan carries more signal than country", s_plan > s_country,
              f"plan {s_plan:.4f} vs country {s_country:.4f}")
    if REF:
        for col, want in [("plan", {"basic": (89977, .1526), "standard": (70123, .0973),
                                    "premium": (39900, .0812)}),
                          ("payment_method", {"card": (110411, .1132), "wallet": (55785, .1132),
                                              "prepaid": (33804, .1475)})]:
            g = subs.groupby(col).churned_next_30d.agg(["count", "mean"])
            for k, (n_want, r_want) in want.items():
                n_got, r_got = int(g.loc[k, "count"]), float(g.loc[k, "mean"])
                check(f"C11 {col}={k} count", abs(n_got - n_want) <= max(1, 0.01 * n_want),
                      f"{n_got:,} vs {n_want:,}")
                check(f"C11 {col}={k} churn", abs(r_got - r_want) <= 0.01 * r_want + 0.002,
                      f"{r_got:.4f} vs {r_want:.4f}")
        tb = pd.cut(subs.tenure_months, [0, 6, 12, 24, 36, 999],
                    labels=["0-6", "7-12", "13-24", "25-36", "37+"])
        g = subs.groupby(tb, observed=True).churned_next_30d.mean()
        check("C11 tenure churn is monotonically decreasing",
              all(g.iloc[i] > g.iloc[i + 1] for i in range(len(g) - 1)),
              " > ".join(f"{v:.4f}" for v in g))

failed = [n for n, p, _ in results if not p]
print(f"\n{'=' * 72}")
print(f"  {len(results) - len(failed)}/{len(results)} passed" +
      (f" — FAILED: {', '.join(failed)}" if failed else " — ALL PASS"))
print("=" * 72)
sys.exit(1 if failed else 0)
