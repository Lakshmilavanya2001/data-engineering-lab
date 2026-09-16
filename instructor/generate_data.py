#!/usr/bin/env python3
"""
generate_data.py — synthetic streaming-service dataset for the PCAI hands-on lab.

Produces two artifacts that MUST be generated together (shared RNG seed), because
the churn label in `subscribers` is causally linked to behaviour in `watch_events`:

  out/subscribers.csv            200,000 rows   -> seeded into Postgres (app_db.public)
  out/watch_events/dt=YYYY-MM-DD/events.csv
                                 ~20M rows total across 180 daily files (~1.1 GB)
                                                 -> uploaded to the PCAI Data Volume

Causal order (this is what makes the model learnable rather than fake):
    plan/tenure/tickets -> latent engagement -> event rate + recency skew
    engagement + tickets + tenure + plan + payment -> churn probability -> label

Deliberate noise columns: country, device. Feature importance should show them at
~zero, which is a five-minute teaching moment about models finding what is there.

Runtime ~3 min, peak RAM ~3 GB. Run once, from any notebook.
"""

import os
import numpy as np
import pandas as pd
from datetime import date, timedelta

# ─────────────────────────── knobs ───────────────────────────
SEED          = 42
N_SUBS        = 200_000
N_DAYS        = 180
N_TITLES      = 2_000
START         = date(2026, 1, 1)
TARGET_CHURN  = 0.12      # calibrated exactly, see calibrate_intercept()
RECENCY_SKEW  = 1.35      # >1 pushes churner activity earlier, so churners look
                          # inactive in the final 30 days. Measured test AUC:
                          #   1.20 -> 0.85     1.35 -> 0.87     1.60 -> 0.90
                          # 1.35 is satisfying without being a giveaway.
OUT_DIR       = "out"
EVENTS_DIR    = os.path.join(OUT_DIR, "watch_events")

rng = np.random.default_rng(SEED)


def calibrate_intercept(base_logit, target):
    """Bisect an intercept offset so mean(sigmoid(base + offset)) == target."""
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if (1 / (1 + np.exp(-(base_logit + mid)))).mean() < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ═══════════════════ 1. subscribers (the Postgres side) ═══════════════════
print("Generating subscribers ...")

sub_id  = np.arange(1, N_SUBS + 1, dtype=np.int32)
plan    = rng.choice(["basic", "standard", "premium"], N_SUBS, p=[0.45, 0.35, 0.20])
country = rng.choice(["US", "IN", "BR", "DE", "GB", "JP"], N_SUBS,
                     p=[0.30, 0.25, 0.15, 0.12, 0.10, 0.08])          # pure noise
payment = rng.choice(["card", "wallet", "prepaid"], N_SUBS, p=[0.55, 0.28, 0.17])
tenure  = rng.integers(1, 60, N_SUBS).astype(np.int16)                 # months
tickets = rng.poisson(0.35, N_SUBS).clip(0, 9).astype(np.int16)

price = np.select([plan == "basic", plan == "standard"], [6.99, 12.99], default=18.99)

# latent engagement -> drives how much they watch
engagement = (0.35 * (plan == "premium")
              + 0.15 * (plan == "standard")
              + 0.012 * tenure
              - 0.10  * tickets
              + rng.normal(0, 1, N_SUBS))
eng_z = (engagement - engagement.mean()) / engagement.std()

base_logit = (-1.35 * eng_z
              + 0.50 * tickets
              - 0.020 * tenure
              + 0.45 * (plan == "basic")
              + 0.40 * (payment == "prepaid"))
base_logit = base_logit + calibrate_intercept(base_logit, TARGET_CHURN)

churn = (rng.random(N_SUBS) < 1 / (1 + np.exp(-base_logit))).astype(np.int8)

signup = np.array([START - timedelta(days=int(t) * 30) for t in tenure])

subs = pd.DataFrame({
    "subscriber_id":       sub_id,
    "signup_date":         signup,
    "plan":                plan,
    "country":             country,
    "payment_method":      payment,
    "monthly_price":       price.round(2),
    "support_tickets_90d": tickets,
    "tenure_months":       tenure,
    "churned_next_30d":    churn,
})

os.makedirs(OUT_DIR, exist_ok=True)
subs.to_csv(os.path.join(OUT_DIR, "subscribers.csv"), index=False)
print(f"  subscribers.csv  {len(subs):,} rows   churn rate {churn.mean():.4f}")


# ═══════════════════ 2. watch_events (the object-store side) ═══════════════════
print("Generating watch events ...")

# events/day per subscriber, driven by the same latent engagement
lam    = np.clip(0.55 + 0.30 * eng_z, 0.05, None)
counts = rng.poisson(lam * N_DAYS).astype(np.int64)
total  = int(counts.sum())
print(f"  {total:,} events  ({total / N_SUBS:.0f} per subscriber)")

ev_sub   = np.repeat(sub_id, counts)
ev_churn = np.repeat(churn, counts)
ev_engz  = np.repeat(eng_z.astype(np.float32), counts)

# Recency skew: churners' activity concentrates early and tapers off, so their
# last-30-day watch time is low. This is the signal the feature SQL will surface.
u      = rng.random(total)
p_exp  = np.where(ev_churn == 1, RECENCY_SKEW, 1.0)
day_ix = np.minimum((u ** p_exp * N_DAYS).astype(np.int16), N_DAYS - 1)
del u, p_exp, ev_churn

watch     = np.clip(rng.lognormal(3.2, 0.75, total), 1, 240).astype(np.float32)
completed = (rng.random(total) < (0.45 + 0.075 * np.clip(ev_engz, -2, 2))).astype(np.int8)
content   = rng.integers(1, N_TITLES + 1, total).astype(np.int32)
dev_code  = rng.choice(4, total, p=[0.42, 0.31, 0.19, 0.08]).astype(np.int8)  # noise
DEVICES   = np.array(["mobile", "tv", "web", "tablet"])
del ev_engz

# sort by day so each daily file is one contiguous slice
order  = np.argsort(day_ix, kind="stable")
day_ix = day_ix[order]
bounds = np.searchsorted(day_ix, np.arange(N_DAYS + 1))

os.makedirs(EVENTS_DIR, exist_ok=True)
for d in range(N_DAYS):
    lo, hi = bounds[d], bounds[d + 1]
    if lo == hi:
        continue
    ix  = order[lo:hi]
    dt  = START + timedelta(days=d)
    day = os.path.join(EVENTS_DIR, f"dt={dt.isoformat()}")
    os.makedirs(day, exist_ok=True)
    pd.DataFrame({
        "event_id":      np.arange(lo, hi, dtype=np.int64),
        "subscriber_id": ev_sub[ix],
        "content_id":    content[ix],
        "event_date":    dt.isoformat(),
        "watch_minutes": watch[ix].round(1),
        "device":        DEVICES[dev_code[ix]],
        "completed":     completed[ix],
    }).to_csv(os.path.join(day, "events.csv"), index=False)
    if d % 30 == 0:
        print(f"  day {d:3d}/{N_DAYS}  ({hi - lo:,} rows)")

size_gb = sum(os.path.getsize(os.path.join(r, f))
              for r, _, fs in os.walk(EVENTS_DIR) for f in fs) / 1024**3
print(f"\nDone.  {N_DAYS} daily files, {size_gb:.2f} GB total.")


# ═══════════════════ 3. sanity check: is the signal actually there? ═══════════════════
last30 = day_ix >= (N_DAYS - 30)
mins   = pd.Series(watch[order][last30]).groupby(ev_sub[order][last30]).sum()
joined = subs.set_index("subscriber_id").join(mins.rename("minutes_30d")).fillna(0)
print("\nmean minutes in final 30 days:")
print(f"  non-churners  {joined.loc[joined.churned_next_30d == 0, 'minutes_30d'].mean():8.1f}")
print(f"  churners      {joined.loc[joined.churned_next_30d == 1, 'minutes_30d'].mean():8.1f}")
print("  (churners should be clearly lower — that is the signal the GNN-free model learns)")
