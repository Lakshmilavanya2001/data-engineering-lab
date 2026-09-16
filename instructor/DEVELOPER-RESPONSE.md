# Re: Lab 18 — what is missing. The generator is not missing.

**To:** whoever owns `DEVELOPER-MISSING-FILES.md` (2026-09-15)
**From:** the Lab 18 content owner · **Date:** 2026-09-16
**Status:** M1 closed. No rewrite needed.

`phase0_setup.py` survives. It is attached, it is the original, and it now satisfies
your §3 interface contract. Your §5 question 1 — *"does it still exist somewhere?"* —
is the one that mattered, and the answer is yes.

---

## 1. Proof it is the original, not a reconstruction

Your acceptance test A1 requires the manifest `run_id` to be `219e36766df2` for the
reference configuration. The script derives that id by hashing its own config block.
Run it and you get exactly that value. Nothing was tuned to make this true — the id is
a SHA-256 prefix, so it either matches or it does not.

The stronger proof is §2.2. Your spec inferred those distributions from the recorded
query results and asked for a match **within ±1 %**. A full regeneration on 2026-09-16
reproduces them **exactly**, to four decimal places:

| your §2.2 target | regenerated | |
|---|---|---|
| plan: basic 89,977 · standard 70,123 · premium 39,900 | 89,977 · 70,123 · 39,900 | exact |
| plan churn: 0.1526 · 0.0973 · 0.0812 | 0.1526 · 0.0973 · 0.0812 | exact |
| payment: card 110,411 · wallet 55,785 · prepaid 33,804 | 110,411 · 55,785 · 33,804 | exact |
| payment churn: 0.1132 · 0.1132 · 0.1475 | 0.1132 · 0.1132 · 0.1475 | exact |
| base rate 0.1190 | 0.1190 | exact |
| country spread 0.0049 | 0.0049 | exact |
| plan spread 0.0715 | 0.0715 | exact |
| tenure monotonic 0.2070 → 0.0687 | 0.2070 > 0.1826 > 0.1484 > 0.1097 > 0.0687 | exact |
| 20,010,929 rows · 180 files · 849 MB | same | exact |
| churners 205 min vs stayers 577 min | same | exact |

A rewrite inferred from the artefacts would have had to land a causal label structure
on all of those by construction. This did not have to.

---

## 2. Your §5 questions, answered

**Q1 — does the original exist?** Yes. `instructor/phase0_setup.py` in the lab repo.

**Q2 — `monthly_price`, `device`, `content_id` distributions.** They were never recorded
anywhere because they are not part of any lesson. From the source:

| field | construction |
|---|---|
| `monthly_price` | deterministic from `plan`: basic 6.99, standard 12.99, premium 18.99 |
| `device` | mobile 42 %, tv 31 %, web 19 %, tablet 8 % — **planted noise, like `country`** |
| `content_id` | uniform over a 2,000-title catalogue (`n_titles`) |

`device` being noise matters: it is the second planted column, and the guide says so.

**Q3 — the ~110 subscribers with ≥ 4 tickets.** Intended. Tickets are Poisson(0.35)
clipped to [0, 9], so the tail is the distribution's own, not a seeded special case. It
changes no lesson, and query A4's `HAVING count(*) > 200` hides it on purpose.

**Q4 — a small classroom variant.** Already works, and is now tested. `--days 10
--subscribers 5000` produces a valid dataset in **0.49 s at 83 MB peak RSS**. Its
`run_id` differs (`87ad108a2b94`), which is correct — the id is a function of the
configuration, and that is what stops a reduced dataset being mistaken for the reference.

---

## 3. §3 contract — what changed today

| id | requirement | before | now |
|---|---|---|---|
| G1 | CLI: `--out-root`, pg coords, seed/days/end-date/events/subscribers; stages `generate\|seed\|verify\|all` | env vars + a different stage set | **done.** `seed` accepts as an alias of `postgres`; old flags still work |
| G2 | password from `PGPASSWORD` only, never a flag, never printed | defaulted to a literal | **done** (2026-09-16). Exits with instructions if unset; checked late so `--help` still works |
| G3 | exit 0 on success, non-zero with the failing check named on stderr | exited 1, but named the check on stdout | **done.** `phase0_setup: FAILED — <check>` on stderr |
| G4 | writes only `raw/watch_events/dt=*/events.csv` and `manifest.json`; never `curated/` | manifest was `raw/_manifest.json` | **done.** Manifest moved to `<out-root>/manifest.json`; the old path is still *read* so an existing dataset is recognised. It also writes `raw/subscribers.csv` — see §4 |
| G5 | world-readable for a different reading uid | default umask | **done.** 0644/0755 applied under the out-root after generation |
| G6 | numpy/pandas/pyarrow/psycopg2 only | imported boto3 unconditionally | **done.** boto3 only for `--stage s3`. `requirements.txt` included |
| G7 | idempotent, converges to the same bytes | manifest guard + DROP/CREATE | **verified.** Two independent full runs produce identical per-file sha256 |
| G8 | manifest: seed, days, end date, counts, per-file counts **and checksums**, library versions, `run_id` | had run_id, config and counts | **done.** Now also `files[]` with per-day rows/bytes/sha256, `python`, `libraries`, `expected_events` |
| G9 | `GRANT SELECT`, checked by verify with `has_table_privilege` | already did both | **was already met** |
| G10 | verify re-checks Stage 0 rows 0.1–0.5, PASS/FAIL per row, no regeneration | 4 of 5 rows | **done.** Added the base-rate row (0.5), an independent on-disk row count, and an `--events` target check |
| G11 | 1–4 CPU / 2–8 GiB; stream, do not build one 20 M-row frame | ~3 GB peak | **done.** 845 MB peak RSS, 46 s wall, full scale. It never built a 20 M-row DataFrame — it built 20 M-element arrays; removing one intermediate cut the peak by a third |
| G12 | no hardcoded lab paths | probed `~/shared`, printed PCAI next-steps | **done.** `--out-root` wins; the PCAI-specific epilogue is gone |

Measured on this box, Python 3.12.3, numpy 2.5.3, pandas 3.0.5.

---

## 4. Two things to decide, not defects

1. **`raw/subscribers.csv`.** G4 lists only the event files and the manifest, but the
   generator also writes the 200,000-row subscriber CSV under the out-root. It is the
   input to the `seed` stage and the reason `verify` can check distributions with no
   database. Say if you want it suppressed after seeding; I would keep it.
2. **`--events` is checked, not applied.** The event count is emergent from the seeded
   Poisson draw, not an input. Making it an input would change the generator's output
   and therefore the `run_id`, breaking A1. So it is recorded in the manifest and
   asserted: pass `--events 20010929` and a mismatch fails both generate and verify.
   Your Job can keep passing it unchanged.

---

## 5. Acceptance status

`test_phase0.py` (your §4, groups A–C) is included and passes against a full
regeneration: **32 of 32**. Against a reduced CI dataset: **14 of 14** — the
statistical checks scale their tolerance with sample size, because at n=5,000 the
country spread cannot be 10× below the plan spread and a test that fails on valid data
is a broken test.

```
python3 phase0_setup.py --stage generate --out-root /tmp/small \
    --seed 42 --days 10 --subscribers 5000 --end-date 2026-06-29
python3 test_phase0.py --out-root /tmp/small --reduced      # seconds, no database
```

**Group D is yours.** It needs the curate Job, a notebook and MLflow on bcm-compute,
none of which I can reach. The gate is unchanged: notebook Part 5b must print
`ALL PASS`, and Part 3 must squash to 196,564.

---

## 6. Where to put it

Your CI watches `labs/data-engineering/tools/**`. Drop in:

```
labs/data-engineering/tools/phase0_setup.py
labs/data-engineering/tools/test_phase0.py
labs/data-engineering/tools/requirements.txt
```

No chart or Job change is needed — the CLI matches what `seed-job.yaml` already calls.

On your remaining items: **M2** falls out of M1. **M3** is included. **M5** is done for
PCAI (27 screenshots and an architecture diagram exist in `guide/`) but they show the
PCAI access path, so Wave 3 still needs re-takes. **M6** is real — `guide/build/content.py`
reads `setup_notebook_env.sh` from an absolute path; a one-line fix I will take with the
Wave 3 guide pass unless you want it sooner.
