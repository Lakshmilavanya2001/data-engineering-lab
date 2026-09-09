# From measured result to value statement

The last exercise of the lab. You have a set of numbers you measured yourself. This turns
them into sentences a customer will act on. The rule: **every value statement traces back
to a number you can reproduce in front of them.**

## The three-line structure

Every statement has exactly three parts. Write all three, then say only the third.

| Line | Question it answers | Example |
|---|---|---|
| **Technical result** | What did you measure? | The 20 M-row aggregation took 18 s on CPU and 0.4 s on the GPU |
| **What it means** | What does that change about the work? | A feature build that was a coffee break is now interactive |
| **Value statement** | Why does the customer care? | Your data scientists can try ten feature ideas in the time it used to take to try one |

The mistake is to say line 1 to a customer. The other mistake is to say line 3 without
having line 1 behind it.

## Worked examples from this lab

Fill in *your* numbers. The reference values are shown so you know what "normal" looks like.

### Columnar storage (Spark → Parquet)
- **Result:** [849 MB] of CSV became [232 MB] of Parquet — [3.66×] smaller; the model needs 4 of
  8 columns and reads only those.
- **Meaning:** every downstream read touches a fraction of the bytes; storage cost and read
  time both fall without touching the data itself.
- **Value:** the same analytics run on a third of the storage and the reads that used to be the
  bottleneck stop being one — before buying anything faster.

### Federation (EzPresto over Postgres)
- **Result:** the cancellation label was read live from the customer database; zero rows were
  copied; query time [x s].
- **Meaning:** no nightly export, no stale copy, no second system of record to secure.
- **Value:** your data science team can use the customer database without ever holding a copy
  of it — the compliance conversation gets shorter, not longer.

### cuDF — the aggregation (CUDA-X: "20× faster pandas")
- **Result:** identical `groupby` code, [t_cpu s] on CPU vs [t_gpu s] on GPU — [N×].
  Output validated identical (Part 5b).
- **Meaning:** the feature-engineering loop is now interactive; the code did not change.
- **Value:** nothing to rewrite, nobody to retrain; the existing pandas skills of the team get
  [N×] faster on the day the hardware arrives.

### cuML — the model (CUDA-X: "50× faster scikit-learn")
- **Result:** RandomForest, same parameters, [t_cpu s] vs [t_gpu s] — [N×]; AUC [a] vs [b]
  (same within noise).
- **Meaning:** hyper-parameter search across hundreds of configurations fits in an afternoon.
- **Value:** more candidate models per week means better models in production sooner, at the
  same headcount.

### cuVS — lookalike search (CUDA-X vector search)
- **Result:** every held-out subscriber matched to its 10 nearest labelled neighbours across
  [150,000] vectors — [t_cpu s] CPU brute force vs [t_gpu s] GPU; identical neighbours
  (recall [0.99+]). The model-free "share of churned neighbours" score alone reaches
  AUC [~0.8].
- **Meaning:** lookalike targeting over the whole customer base is a sub-second query, not a
  batch job.
- **Value:** the retention team can ask "who looks like the people who left last month?" and
  get an answer while they are still in the meeting.

### The pipeline as a whole
- **Result:** raw events + customer database → registered model, [~15 min] per participant,
  every step validated, every run recorded with its parameters and score.
- **Meaning:** the path from data to a deployable model is repeatable by someone who is not
  the person who built it.
- **Value:** the first model is not the achievement; the *second* one, next month, built by a
  different person in an afternoon, is.

## What you must not say

- Any speed-up you did not measure on the data in front of you. Vendor headline numbers
  ("20×", "50×") are ceilings measured on chosen workloads; yours is the honest one.
- "Faster" without saying faster *than what* — how many CPU cores, which library version.
- Anything about country or device. They carry no signal. If asked, say so and show the spread.
- "AI" when you mean "a gradient-boosted tree on twelve columns."

## Your turn — the deliverable

Write **three** value statements from your own run, one paragraph each, using the three-line
structure. At least one must be about a data-engineering result (storage, federation,
validation), not acceleration. Read the value line out loud to the person next to you: if they
ask "compared to what?", go back to line 1.
