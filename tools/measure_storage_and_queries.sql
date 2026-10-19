-- =====================================================================
-- tools/measure_storage_and_queries.sql   (Week 9: architecture memo)
-- Turns the estimates of Week9_Architecture_Shkirpan.md section 2.3 into
-- measurements on any PostgreSQL that holds the project database.
--
--   psql -d ped_safety -f tools/measure_storage_and_queries.sql
--   (Windows: add -U postgres;  to keep the evidence: > docs/evidence/week9/storage_and_queries.log)
--
-- Read-only. Reports the server version, the size of the database and of
-- every table, row counts, and EXPLAIN (ANALYZE) of the three views the
-- analysis and the dashboard read. Nothing is written to the database.
-- =====================================================================
\pset footer off
\timing off

SELECT version();

-- 1. Whole database on disk
SELECT current_database() AS database,
       pg_size_pretty(pg_database_size(current_database())) AS size_on_disk,
       pg_database_size(current_database()) AS bytes;

-- 2. Every table: rows (exact), table bytes, index bytes, total
SELECT c.relname AS "table",
       (xpath('/row/n/text()', query_to_xml('SELECT count(*) AS n FROM ' || c.relname, false, true, '')))[1]::text::bigint AS rows,
       pg_size_pretty(pg_table_size(c.oid))    AS table_size,
       pg_size_pretty(pg_indexes_size(c.oid))  AS index_size,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY pg_total_relation_size(c.oid) DESC;

-- 3. Bookkeeping growth per run (how much a semester of runs adds)
SELECT (SELECT count(*) FROM etl_run)           AS runs,
       (SELECT count(*) FROM etl_log)           AS etl_log_rows,
       (SELECT count(*) FROM validation_result) AS validation_rows,
       (SELECT count(*) FROM source_file)       AS source_file_rows,
       (SELECT count(*) FROM rejected_record)   AS rejected_rows;

-- 4. Query timings on the full data (planner choices and actual time)
\echo
\echo '--- v_ped_transactions: full scan (what the mining step reads) ---'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT * FROM v_ped_transactions;

\echo
\echo '--- v_county_rate: 67 county rates (Objective 3) ---'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT * FROM v_county_rate;

\echo
\echo '--- v_dash_pattern_county: what the dashboard role reads ---'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT * FROM v_dash_pattern_county;

\echo
\echo '--- fingerprint of every stored data row (what preflight and finalize compute) ---'
EXPLAIN (ANALYZE, SUMMARY)
SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM pedestrian t;
