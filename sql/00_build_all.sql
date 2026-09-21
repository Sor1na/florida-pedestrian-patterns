-- =====================================================================
-- 00_build_all.sql   builds the whole database with one command
--
--   createdb ped_safety
--   psql -d ped_safety -v ON_ERROR_STOP=1 -f sql/00_build_all.sql
--
-- Run it from the repository root. It rebuilds from nothing every time:
-- the schema is dropped first, so never point it at a database that holds
-- anything you want to keep. The whole build is one transaction, so a
-- failure leaves the database exactly as it was.
-- =====================================================================
\set ON_ERROR_STOP on
SET client_min_messages = warning;   -- keeps the log free of "drop cascades to ..." notices on a rebuild
BEGIN;

DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;

\ir 01_schema.sql
\ir 02_cardinality_triggers.sql
\ir 03_indexes.sql
\ir 04_views.sql
\ir 06_seed_county.sql
\ir 07_seed_codes.sql
\ir 08_load_data_dictionary.sql
\ir 05_roles.sql

COMMIT;

\echo
\echo Build finished. Objects created:
SELECT CASE c.relkind WHEN 'r' THEN 'tables' WHEN 'v' THEN 'views' WHEN 'i' THEN 'indexes' END AS objects,
       count(*) AS how_many
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'i')
GROUP BY 1 ORDER BY 1;

SELECT CASE contype WHEN 'p' THEN '1 PRIMARY KEY' WHEN 'f' THEN '2 FOREIGN KEY' WHEN 'u' THEN '3 UNIQUE'
                    WHEN 'c' THEN '4 CHECK' WHEN 'x' THEN '5 EXCLUDE' WHEN 't' THEN '6 constraint trigger' END AS constraints,
       count(*) AS how_many
FROM pg_constraint WHERE connamespace = 'public'::regnamespace
GROUP BY 1
UNION ALL
SELECT '7 NOT NULL columns', count(*)
FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema, table_name)
WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' AND c.is_nullable = 'NO'
ORDER BY 1;
