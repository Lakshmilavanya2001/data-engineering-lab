#!/usr/bin/env python3
"""
curate_events.py — the Spark half of the lab's data engineering.

Raw daily CSV  ->  cleaned, partitioned Parquet.

    spark-submit curate_events.py <student_id> <raw_path> <out_path>

Deliberately shows four things students can SEE in the Spark UI:
  1. input partitions  — one task per daily file, so 180 files = real parallelism
  2. an explicit schema — no inference pass, so Spark reads the data exactly once
  3. a shuffle          — dropDuplicates is the expensive stage; point at it in the UI
  4. controlled output  — repartition by `dt` gives one file per day, not thousands

Aggregation is deliberately NOT done here. The notebook does it on the GPU with cuDF
(the RAPIDS demo), then joins to the Postgres `subscribers` table read via EzPresto.
This job's one job is the format lesson: 849 MB of CSV -> ~225 MB of columnar Parquet.

Reads and writes the shared volume, so Spark needs no S3 credentials. Paths come in as
arguments -- the script is storage-agnostic.
"""

import sys
from pyspark.sql import SparkSession, functions as F, types as T

if len(sys.argv) != 4:
    sys.exit("usage: curate_events.py <student_id> <raw_path> <out_path>")

student_id, raw_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

spark = (SparkSession.builder
         .appName(f"curate-events-student-{student_id}")
         .getOrCreate())
spark.sparkContext.setLogLevel("WARN")

print(f"[curate] student   : {student_id}")
print(f"[curate] reading   : {raw_path}")
print(f"[curate] writing   : {out_path}")

# ── 1. explicit schema ────────────────────────────────────────────────────────
# Without this, Spark makes an extra full pass over 20M rows just to guess types.
# `dt` is NOT listed: Spark discovers it from the dt=YYYY-MM-DD directory names
# and appends it automatically. Partition column vs data column — worth one slide.
SCHEMA = T.StructType([
    T.StructField("event_id",      T.LongType(),    False),
    T.StructField("subscriber_id", T.IntegerType(), False),
    T.StructField("content_id",    T.IntegerType(), False),
    T.StructField("event_date",    T.DateType(),    False),
    T.StructField("watch_minutes", T.DoubleType(),  False),
    T.StructField("device",        T.StringType(),  False),
    T.StructField("completed",     T.IntegerType(), False),
])

raw = (spark.read
       .option("header", True)
       .schema(SCHEMA)
       .csv(raw_path))

print(f"[curate] input partitions: {raw.rdd.getNumPartitions()}  "
      f"(one per daily file — this is your parallelism)")

# ── 2. clean ──────────────────────────────────────────────────────────────────
# dropDuplicates forces a full shuffle. It is the most expensive stage in this job
# and the one to point at in the Spark UI: 20M rows redistributed across executors
# so that identical event_ids land together.
clean = (raw
         .dropDuplicates(["event_id"])
         .filter(F.col("subscriber_id").isNotNull())
         .filter((F.col("watch_minutes") > 0) & (F.col("watch_minutes") <= 240))
         .withColumn("is_long_view", (F.col("watch_minutes") >= 30).cast("int")))

# ── 3. write ──────────────────────────────────────────────────────────────────
# repartition by `dt` first, so partitionBy emits ONE file per day instead of one
# file per (day x executor). That is the small-files problem, avoided on purpose.
(clean
 .repartition(F.col("dt"))
 .write
 .mode("overwrite")
 .partitionBy("dt")
 .parquet(out_path))

# ── 4. report ─────────────────────────────────────────────────────────────────
written = spark.read.parquet(out_path)
n_rows  = written.count()
n_subs  = written.select("subscriber_id").distinct().count()
n_days  = written.select("dt").distinct().count()

print("=" * 60)
print(f"[curate] rows written    : {n_rows:,}")
print(f"[curate] subscribers     : {n_subs:,}")
print(f"[curate] day partitions  : {n_days}")
print(f"[curate] output          : {out_path}")
print("=" * 60)

spark.stop()
