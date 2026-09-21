-- =====================================================================
-- tools/export_data_dictionary.sql
-- Writes docs/data_dictionary.md from the live database: types, nullability, and
-- keys come from the PostgreSQL catalog; the words come from the data_dictionary
-- table. Run from the repository root:
--     psql -d ped_safety -f tools/export_data_dictionary.sql
-- =====================================================================
\pset format unaligned
\pset tuples_only on
\pset pager off
\o docs/data_dictionary.md
WITH cols AS (
    SELECT c.table_name::text, c.column_name::text, c.ordinal_position,
           CASE WHEN c.data_type = 'numeric' AND c.numeric_precision IS NOT NULL
                THEN format('numeric(%s,%s)', c.numeric_precision, c.numeric_scale)
                WHEN c.data_type = 'timestamp with time zone' THEN 'timestamptz'
                ELSE c.data_type END AS data_type,
           c.is_nullable,
           t.table_type
    FROM information_schema.columns c
    JOIN information_schema.tables t USING (table_schema, table_name)
    WHERE c.table_schema = 'public' AND c.table_name NOT LIKE 'v\_dq\_%'
), keys AS (
    SELECT rel.relname::text AS table_name, att.attname::text AS column_name,
           string_agg(DISTINCT CASE con.contype WHEN 'p' THEN 'PK'
                                       WHEN 'f' THEN 'FK > ' || frel.relname
                                       WHEN 'u' THEN 'UQ' END, ', ' ORDER BY
                      CASE con.contype WHEN 'p' THEN 'PK' WHEN 'f' THEN 'FK > ' || frel.relname WHEN 'u' THEN 'UQ' END DESC) AS key_role
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
    LEFT JOIN pg_class frel ON frel.oid = con.confrelid
    WHERE con.connamespace = 'public'::regnamespace AND con.contype IN ('p', 'f', 'u')
    GROUP BY rel.relname, att.attname
), tables AS (
    SELECT table_name, table_type,
           row_number() OVER (ORDER BY CASE table_name
               WHEN 'crash' THEN 1 WHEN 'vehicle' THEN 2 WHEN 'pedestrian' THEN 3 WHEN 'ped_crash_type' THEN 4
               WHEN 'county' THEN 5 WHEN 'county_population' THEN 6 WHEN 'block_group' THEN 7
               WHEN 'pbcat_group' THEN 8 WHEN 'pbcat_type' THEN 9 WHEN 'code_lookup' THEN 10
               WHEN 'etl_run' THEN 11 WHEN 'source_file' THEN 12 WHEN 'etl_log' THEN 13 WHEN 'validation_result' THEN 14
               WHEN 'data_dictionary' THEN 15 WHEN 'v_ped_transactions' THEN 16 WHEN 'v_county_rate' THEN 17 ELSE 18 END) AS t_order
    FROM (SELECT DISTINCT table_name, table_type FROM cols) x
), lines AS (
    SELECT 0 AS t_order, 0 AS l_order, 0 AS c_order,
           E'# Data dictionary\n\nGenerated from the live database by `tools/export_data_dictionary.sql`. Types, nullability, and keys come from the PostgreSQL catalog; definitions, sources, allowable values, the meaning of NULL, and sensitivity come from the `data_dictionary` table (loaded from `docs/data_dictionary.csv`). The view `v_dq_undocumented_column` returns a row for any column that is missing here.\n\nSensitivity levels. **Public**: published reference data or counts. **Internal**: pipeline bookkeeping. **Restricted**: case-level values about a real death; they stay in the local database and only aggregates leave it.\n\nKey column: PK = part of the primary key, FK > t = foreign key to table t, UQ = unique.' AS line
    UNION ALL
    SELECT t_order, 1, 0,
           format(E'\n## %s%s\n\n| Column | Type | NULL? | Key | Definition | Source | Allowable values | Meaning of NULL | Sensitivity |\n|---|---|---|---|---|---|---|---|---|',
                  table_name, CASE WHEN table_type = 'VIEW' THEN ' (view)' ELSE '' END)
    FROM tables
    UNION ALL
    SELECT t.t_order, 2, c.ordinal_position,
           format('| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |',
                  c.column_name, c.data_type,
                  CASE WHEN c.is_nullable = 'YES' AND t.table_type = 'BASE TABLE' THEN 'yes' WHEN t.table_type = 'VIEW' THEN 'view' ELSE 'no' END,
                  COALESCE(k.key_role, ''),
                  replace(d.definition, '|', '/'), replace(d.source, '|', '/'), replace(d.allowable_values, '|', '/'),
                  replace(d.null_meaning, '|', '/'), replace(d.sensitivity, '|', '/'))
    FROM cols c
    JOIN tables t USING (table_name)
    LEFT JOIN keys k USING (table_name, column_name)
    LEFT JOIN data_dictionary d USING (table_name, column_name)
)
SELECT line FROM lines ORDER BY t_order, l_order, c_order;
\o
\pset tuples_only off
\pset format aligned
\echo Wrote docs/data_dictionary.md
