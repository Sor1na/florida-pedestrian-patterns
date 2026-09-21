-- =====================================================================
-- 08_load_data_dictionary.sql
-- Loads docs/data_dictionary.csv into the data_dictionary table.
-- \copy reads the file on the client side, relative to the folder psql was
-- started in, so run the build from the repository root.
-- =====================================================================
\copy data_dictionary (table_name, column_name, definition, source, allowable_values, null_meaning, sensitivity) FROM 'docs/data_dictionary.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

-- Copy the definitions into the catalog as well, so \d+ and pgAdmin show them.
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT table_name, column_name, definition FROM data_dictionary LOOP
        EXECUTE format('COMMENT ON COLUMN %I.%I IS %L', r.table_name, r.column_name, r.definition);
    END LOOP;
END;
$$;
