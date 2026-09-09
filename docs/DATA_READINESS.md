# Data-Readiness Explanation — customer-facing

This is the page you hand to a customer's business owner *before* anyone talks about models.
It answers one question: **is this data ready to predict churn, and how do we know?**
Written for someone who owns the outcome, not the platform. No tool names in the first half.

Fill the bracketed values from *your* run. Never quote the reference numbers to a customer.

---

## 1. What we were asked

> Will this subscriber cancel in the next 30 days?

To answer that, we need one table with **one row per subscriber**, describing what they did
recently, and **whether they actually cancelled**. That table did not exist. It had to be built.

## 2. What we started with

| | What it is | Where it lived | Rows | Contains the answer? |
|---|---|---|---|---|
| Viewing activity | every viewing session, 180 days | files in storage | [20,010,929] | No |
| Customer records | plan, tenure, support history, cancellation | the customer database | [200,000] | **Yes** |

Neither is usable alone. Activity says what people did but not what happened to them.
Records say what happened but not what people did. The value is in joining them, and the
join is where data quietly goes wrong.

## 3. What we did to it — in plain terms

1. **Cleaned the activity log.** Removed duplicate events, impossible durations, and orphaned
   records. Converted it to a compact analytical format ([3.66×] smaller) so that every later
   step reads only what it needs.
2. **Summarised 180 days of behaviour into one line per person** for the most recent 30 days:
   minutes watched, number of sessions, how often they finish what they start, how many
   different titles.
3. **Attached the outcome** from the customer database, keeping every customer — including
   the [3,436] who watched nothing in the last 30 days.
4. **Checked every step** against a written checklist (row counts, ranges, duplicates, missing
   values) before moving on. [All / N of N] checks passed.

## 4. Why "keeping every customer" is the headline

The people who watched **nothing** in the last 30 days are the most likely to cancel:
[63%] of them did, against [12%] of everyone else. A standard join would have silently
dropped them because they had no activity to join to. The pipeline keeps them on purpose
and records their activity as zero. **Silence is the strongest signal in this dataset**, and
the easiest one to lose.

## 5. What the data can and cannot tell you

**It can:** rank current subscribers by likelihood of cancelling in the next 30 days, with a
held-out accuracy of [AUC 0.87] — meaning that given one future canceller and one future
stayer, it picks the right one [87]% of the time.

**What drives it, in order:** recent engagement (how much and how varied), support tickets,
plan tier, tenure, payment method.

**It cannot:** explain *why* someone disengaged, distinguish churn from a paused
subscription, or see anything that happened outside the platform. And two fields customers
often ask about — country and device — carry **no signal at all** in this data. We tested for
that specifically.

## 6. Readiness verdict

| Question | Answer |
|---|---|
| Is the outcome recorded for enough history? | Yes — [200,000] labelled customers, [11.9]% positive rate |
| Is behaviour linked to the outcome without leakage? | Yes — features use only the 30 days *before* the outcome window |
| Are the two sources joined without loss? | Yes — [200,000] in, [200,000] out |
| Are there fields that look useful but are not? | Yes — country, device. Excluded from any business claim |
| Is the result reproducible? | Yes — same inputs, same seed, same numbers; every run is registered |

**Verdict: ready for a first model, and ready for a pilot on live data once the same checks
pass on the customer's own extracts.**

## 7. What we would need from you next

- A read-only connection to the customer database (we never copy it)
- 6+ months of activity history, in whatever format it already exists
- An agreed definition of "cancelled" (a date, not a status flag)
- One business owner to review the top 100 predicted cancellers and say whether they look right
