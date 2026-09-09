-- ═══════════════════════════════════════════════════════════════════════════
-- EzPresto demo queries — exploring `subscribers` before any model exists
-- ═══════════════════════════════════════════════════════════════════════════
-- HOW TO RUN: the worksheet takes ONE statement at a time and REJECTS a
-- trailing semicolon. Copy one block, drop the semicolon, hit Run.
--
-- Expected results below are MEASURED on the real dataset (seed 42), so they
-- will match exactly unless the data is regenerated with different knobs.
-- ═══════════════════════════════════════════════════════════════════════════


-- ───────────────────────────────────────────────────────────────────────────
-- PART A — the detective story: what predicts churn?
--
-- Run these in order. They build to a punchline in A6.
-- ───────────────────────────────────────────────────────────────────────────

-- A1. How much data is there?
SELECT count(*) AS subscribers
FROM   dataengineeringlab.public.subscribers
-- → 200000


-- A2. How many actually cancelled? (Always establish the base rate first —
--     every later number is only meaningful compared to this one.)
SELECT count(*)                              AS subscribers,
       sum(churned_next_30d)                 AS churned,
       round(avg(churned_next_30d), 4)       AS churn_rate
FROM   dataengineeringlab.public.subscribers
-- → 200000 | 23796 | 0.119     ... so ~12% is "normal"


-- A3. Does the PLAN matter?
SELECT plan,
       count(*)                        AS people,
       round(avg(churned_next_30d), 4) AS churn_rate
FROM   dataengineeringlab.public.subscribers
GROUP  BY plan
ORDER  BY churn_rate DESC
-- → basic    89977  0.1526
--   standard 70123  0.0973
--   premium  39900  0.0812
-- Basic churns nearly 2x premium. Real signal.


-- A4. Do SUPPORT TICKETS matter? (The clearest relationship in the data.)
SELECT support_tickets_90d,
       count(*)                        AS people,
       round(avg(churned_next_30d), 4) AS churn_rate
FROM   dataengineeringlab.public.subscribers
GROUP  BY support_tickets_90d
HAVING count(*) > 200
ORDER  BY support_tickets_90d
-- → 0 tickets  141001  0.0986
--   1 ticket    49185  0.1536
--   2 tickets    8635  0.2249
--   3 tickets    1069  0.3265
-- Every complaint roughly compounds the risk. Ask the room WHY before showing it.


-- A5. Does TENURE matter? (Bucketing a number is a real analyst move —
--     raw month-by-month is noise; bands show the shape.)
SELECT CASE WHEN tenure_months <=  6 THEN '1. 0-6 mo'
            WHEN tenure_months <= 12 THEN '2. 7-12 mo'
            WHEN tenure_months <= 24 THEN '3. 13-24 mo'
            WHEN tenure_months <= 36 THEN '4. 25-36 mo'
            ELSE                          '5. 37+ mo'
       END                             AS tenure_band,
       count(*)                        AS people,
       round(avg(churned_next_30d), 4) AS churn_rate
FROM   dataengineeringlab.public.subscribers
GROUP  BY 1
ORDER  BY 1
-- → 0-6 mo    20213  0.2070
--   7-12 mo   20597  0.1826
--   13-24 mo  40506  0.1484
--   25-36 mo  41077  0.1097
--   37+ mo    77607  0.0687
-- New customers churn 3x more than long-timers. Monotonic — a very clean signal.


-- A6. *** THE PUNCHLINE *** Does COUNTRY matter?
SELECT country,
       count(*)                        AS people,
       round(avg(churned_next_30d), 4) AS churn_rate
FROM   dataengineeringlab.public.subscribers
GROUP  BY country
ORDER  BY churn_rate DESC
-- → DE 24148 0.1211 | US 60091 0.1197 | IN 49988 0.1191
--   BR 29947 0.1184 | JP 15838 0.1172 | GB 19988 0.1162
--
-- Six countries. Every single one sits at ~0.12 — the base rate.
-- Country predicts NOTHING. It was put in the data as deliberate noise.
--
-- Ask the room: "is Germany worse than Britain?" It LOOKS worse (0.1211 vs
-- 0.1162) until you notice every other column varies by 2-3x and this one
-- varies by half a percent.


-- A7. Prove it with one number instead of eyeballing it.
SELECT round(max(r) - min(r), 4) AS spread
FROM  (SELECT avg(churned_next_30d) AS r
       FROM   dataengineeringlab.public.subscribers
       GROUP  BY country)
-- → 0.0049
-- Now run the same thing for plan: change GROUP BY country to GROUP BY plan
-- → 0.0715  ... a 15x wider spread.
--
-- THIS IS THE LESSON: a useless column is not one that scores zero. It is one
-- whose categories are INDISTINGUISHABLE from each other. You will see the
-- exact same fingerprint in the model's feature importance later.


-- A8. Payment method — a smaller but real effect.
SELECT payment_method,
       count(*)                        AS people,
       round(avg(churned_next_30d), 4) AS churn_rate
FROM   dataengineeringlab.public.subscribers
GROUP  BY payment_method
ORDER  BY churn_rate DESC
-- → prepaid 33804 0.1475 | card 110411 0.1132 | wallet 55785 0.1132
-- Prepaid churns ~30% more. Low commitment, easy to walk away.


-- A9. Two factors at once — where the risk really concentrates.
SELECT plan,
       payment_method,
       count(*)                        AS people,
       round(avg(churned_next_30d), 4) AS churn_rate
FROM   dataengineeringlab.public.subscribers
GROUP  BY plan, payment_method
HAVING count(*) > 1000
ORDER  BY churn_rate DESC
LIMIT  5
-- Basic + prepaid is the worst combination. A model finds this automatically;
-- here you found it by hand, which is the point.


-- ───────────────────────────────────────────────────────────────────────────
-- PART B — what you can do WITHOUT any database access
--
-- Nobody in the room has a Postgres password or a database client.
-- ───────────────────────────────────────────────────────────────────────────

-- B1. What data sources can I reach?
SHOW CATALOGS

-- B2. What is inside this one?
SHOW SCHEMAS FROM dataengineeringlab

-- B3. What tables?
SHOW TABLES FROM dataengineeringlab.public

-- B4. What columns, and what types?
DESCRIBE dataengineeringlab.public.subscribers

-- B5. Same thing as a queryable table — this is metadata AS data.
SELECT column_name, data_type
FROM   dataengineeringlab.information_schema.columns
WHERE  table_name = 'subscribers'
ORDER  BY ordinal_position


-- ───────────────────────────────────────────────────────────────────────────
-- PART C — the honest "why a query engine?" demo
-- ───────────────────────────────────────────────────────────────────────────

-- C1. TWO CATALOGS IN ONE STATEMENT.
--     `dataengineeringlab` is a Postgres database on another machine.
--     `system` is the query engine's own internal catalog.
--     Completely different sources, one SELECT, no copy of either.
SELECT (SELECT count(*) FROM dataengineeringlab.public.subscribers) AS subscribers_in_postgres,
       (SELECT count(*) FROM system.runtime.nodes)                  AS query_engine_nodes

-- C2. A real join across the two.
SELECT n.node_version,
       count(*)                        AS people,
       round(avg(s.churned_next_30d),4) AS churn_rate
FROM   dataengineeringlab.public.subscribers s
CROSS  JOIN system.runtime.nodes n
GROUP  BY n.node_version
-- Contrived on purpose. The POINT is the FROM clause: two different systems,
-- joined in one statement. Swap `system` for a second real database and
-- nothing about how you write the query changes.

-- C3. Every query anyone has run — the engine watching itself.
SELECT query_id, state, substr(query, 1, 60) AS query
FROM   system.runtime.queries
ORDER  BY created DESC
LIMIT  10
