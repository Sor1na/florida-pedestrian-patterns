-- =====================================================================
-- 05_roles.sql   who may read and write what
-- Three group roles, all NOLOGIN: nobody can connect as them, and this file
-- holds no passwords. A person gets a login role of their own, created by hand
-- (see "Setup" in the README), and is then added to one of these groups.
--
--   ped_etl        the pipeline: reads and writes every table
--   ped_analyst    notebooks and mining: reads everything, writes nothing
--   ped_dashboard  Tableau / Plotly: reads aggregates and labels only.
--                  It cannot see person-level rows, case numbers, or coordinates.
--                  This is the proposal's promise ("person-level rows stay in the
--                  local database; only aggregates are published") as a permission.
-- =====================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ped_etl')       THEN CREATE ROLE ped_etl       NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ped_analyst')   THEN CREATE ROLE ped_analyst   NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ped_dashboard') THEN CREATE ROLE ped_dashboard NOLOGIN; END IF;
END;
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ped_etl, ped_analyst, ped_dashboard;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ped_etl;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ped_analyst;

-- The dashboard sees aggregates, reference data, and labels. Nothing else.
-- (A view runs with its owner's rights, so the role needs no access to the tables under it.)
GRANT SELECT ON v_county_rate, v_dash_pattern_county,
                county, county_population, code_lookup, pbcat_group, pbcat_type, data_dictionary
      TO ped_dashboard;
