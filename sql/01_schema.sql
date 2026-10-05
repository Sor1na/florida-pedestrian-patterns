-- =====================================================================
-- Built for Cars, Deadly for Walkers: Florida pedestrian deaths, 2020-2024
-- 01_schema.sql   tables, keys, and column rules
-- Target: PostgreSQL 16 (uses the btree_gist extension that ships with it)
-- Run through sql/00_build_all.sql, not on its own.
--
-- Conventions
--   * Column names are the FARS / EPA / Census names in lower case
--     (so "longitud" is spelled the FARS way on purpose).
--   * Every coded FARS column is NOT NULL. "Unknown" and "not reported" are
--     real codes (8, 9, 98, 99, 998, 999) and stay in the column.
--   * NULL is used only where the source has no usable value at all
--     (coordinates, block group, striking vehicle, transit distance).
--     The data dictionary says what NULL means for each of these.
--   * Every constraint has a name, so a failed load says which rule broke.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- needed for one EXCLUDE constraint (code_lookup)

-- ---------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------

CREATE TABLE county (
    county_fips smallint NOT NULL,
    name        text     NOT NULL,
    CONSTRAINT county_pk      PRIMARY KEY (county_fips),
    CONSTRAINT county_name_uq UNIQUE (name),
    CONSTRAINT county_fips_ck CHECK (county_fips BETWEEN 1 AND 133),
    CONSTRAINT county_name_ck CHECK (name = btrim(name) AND name <> '')
);

CREATE TABLE county_population (
    county_fips smallint NOT NULL,
    year        smallint NOT NULL,
    population  integer  NOT NULL,
    vintage     smallint NOT NULL,
    CONSTRAINT county_population_pk         PRIMARY KEY (county_fips, year),
    CONSTRAINT county_population_county_fk  FOREIGN KEY (county_fips) REFERENCES county (county_fips),
    CONSTRAINT county_population_year_ck    CHECK (year BETWEEN 2020 AND 2024),
    CONSTRAINT county_population_pop_ck     CHECK (population > 0),
    -- an estimate for July 1 of year Y first appears in Vintage Y
    CONSTRAINT county_population_vintage_ck CHECK (vintage BETWEEN year AND 2030)
);

CREATE TABLE block_group (
    geoid10     text NOT NULL,
    -- digits 3-5 of the GEOID are the county, so the column is computed, not typed in.
    -- It cannot disagree with the GEOID, and it still carries a foreign key.
    county_fips smallint NOT NULL GENERATED ALWAYS AS (substring(geoid10 FROM 3 FOR 3)::smallint) STORED,
    natwalkind  numeric(5,2) NOT NULL,
    d3b         numeric(9,3),
    d4a         numeric(9,2),
    totpop      integer NOT NULL,
    CONSTRAINT block_group_pk            PRIMARY KEY (geoid10),
    CONSTRAINT block_group_county_fk     FOREIGN KEY (county_fips) REFERENCES county (county_fips),
    CONSTRAINT block_group_geoid_ck      CHECK (geoid10 ~ '^12[0-9]{10}$'),      -- 12 digits, Florida
    CONSTRAINT block_group_natwalkind_ck CHECK (natwalkind BETWEEN 1 AND 20),
    CONSTRAINT block_group_d3b_ck        CHECK (d3b >= 0),
    CONSTRAINT block_group_d4a_ck        CHECK (d4a >= 0),                       -- EPA's -99999 must arrive as NULL
    CONSTRAINT block_group_totpop_ck     CHECK (totpop >= 0)
);

-- Flat FARS code lists: labels by variable, code, and the years the label is valid.
-- Allowed values themselves are enforced by CHECK constraints on the data tables;
-- this table supplies the words for views, the dashboard, and the dictionary.
CREATE TABLE code_lookup (
    variable   text     NOT NULL,
    code       smallint NOT NULL,
    year_from  smallint NOT NULL DEFAULT 2020,
    year_to    smallint NOT NULL DEFAULT 2024,
    label      text     NOT NULL,
    is_unknown boolean  NOT NULL DEFAULT false,
    CONSTRAINT code_lookup_pk          PRIMARY KEY (variable, code, year_from),
    CONSTRAINT code_lookup_variable_ck CHECK (variable = lower(variable) AND variable <> ''),
    CONSTRAINT code_lookup_years_ck    CHECK (year_from BETWEEN 2020 AND 2024 AND year_to BETWEEN year_from AND 2024),
    CONSTRAINT code_lookup_label_ck    CHECK (label <> ''),
    -- one code cannot have two labels in the same year
    CONSTRAINT code_lookup_no_overlap_ex EXCLUDE USING gist
        (variable WITH =, code WITH =, int4range(year_from, year_to, '[]') WITH &&)
);

-- Pedestrian crash typing (PBCAT) has a hierarchy: every crash type belongs to one
-- crash group. That is a real dependency, so it gets real tables and foreign keys.
CREATE TABLE pbcat_group (
    pedcgp smallint NOT NULL,
    label  text     NOT NULL,
    CONSTRAINT pbcat_group_pk       PRIMARY KEY (pedcgp),
    CONSTRAINT pbcat_group_label_uq UNIQUE (label)
);

CREATE TABLE pbcat_type (
    pedctype smallint NOT NULL,
    label    text     NOT NULL,
    pedcgp   smallint NOT NULL,
    CONSTRAINT pbcat_type_pk       PRIMARY KEY (pedctype),
    CONSTRAINT pbcat_type_label_uq UNIQUE (label),
    CONSTRAINT pbcat_type_group_fk FOREIGN KEY (pedcgp) REFERENCES pbcat_group (pedcgp)
);

-- ---------------------------------------------------------------------
-- FARS data: crash -> vehicle, crash -> pedestrian -> ped_crash_type
-- ---------------------------------------------------------------------

CREATE TABLE crash (
    year      smallint NOT NULL,
    st_case   integer  NOT NULL,
    county    smallint NOT NULL,
    month     smallint NOT NULL,
    day_week  smallint NOT NULL,
    hour      smallint NOT NULL,
    rur_urb   smallint NOT NULL,
    func_sys  smallint NOT NULL,
    reljct2   smallint NOT NULL,
    lgt_cond  smallint NOT NULL,
    weather   smallint NOT NULL,
    latitude  numeric(10,8),
    longitud  numeric(11,8),
    geoid10   text,
    tway_id   text,
    fatals    smallint NOT NULL,
    peds      smallint NOT NULL,
    CONSTRAINT crash_pk             PRIMARY KEY (year, st_case),
    CONSTRAINT crash_county_fk      FOREIGN KEY (county)  REFERENCES county (county_fips),
    CONSTRAINT crash_block_group_fk FOREIGN KEY (geoid10) REFERENCES block_group (geoid10),
    CONSTRAINT crash_year_ck        CHECK (year BETWEEN 2020 AND 2024),
    CONSTRAINT crash_st_case_ck     CHECK (st_case BETWEEN 120001 AND 129999),   -- first two digits = state 12, Florida
    CONSTRAINT crash_month_ck       CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT crash_day_week_ck    CHECK (day_week BETWEEN 1 AND 7),
    CONSTRAINT crash_hour_ck        CHECK (hour BETWEEN 0 AND 23 OR hour = 99),
    CONSTRAINT crash_rur_urb_ck     CHECK (rur_urb IN (1, 2, 6, 8, 9)),
    CONSTRAINT crash_func_sys_ck    CHECK (func_sys IN (1, 2, 3, 4, 5, 6, 7, 96, 98, 99)),
    CONSTRAINT crash_reljct2_ck     CHECK (reljct2 IN (1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 19, 20, 98, 99)),
    CONSTRAINT crash_lgt_cond_ck    CHECK (lgt_cond BETWEEN 1 AND 9),
    CONSTRAINT crash_weather_ck     CHECK (weather IN (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 98, 99)),
    -- a point has both parts or neither; the FARS fillers 77.7777 / 777.7777 etc. fall outside the box
    CONSTRAINT crash_point_both_or_neither_ck CHECK ((latitude IS NULL) = (longitud IS NULL)),
    CONSTRAINT crash_latitude_ck    CHECK (latitude BETWEEN 24.3 AND 31.1),
    CONSTRAINT crash_longitud_ck    CHECK (longitud BETWEEN -87.7 AND -79.8),
    -- business rule 3: a block group only when there is a point to put in it
    CONSTRAINT crash_block_group_needs_point_ck CHECK (geoid10 IS NULL OR latitude IS NOT NULL),
    CONSTRAINT crash_tway_id_ck     CHECK (tway_id = btrim(tway_id) AND tway_id <> ''),
    CONSTRAINT crash_fatals_ck      CHECK (fatals BETWEEN 1 AND 99),
    CONSTRAINT crash_peds_ck        CHECK (peds BETWEEN 1 AND 99)
);

CREATE TABLE vehicle (
    year     smallint NOT NULL,
    st_case  integer  NOT NULL,
    veh_no   smallint NOT NULL,
    body_typ smallint NOT NULL,
    vspd_lim smallint NOT NULL,
    hit_run  smallint NOT NULL,
    CONSTRAINT vehicle_pk          PRIMARY KEY (year, st_case, veh_no),
    CONSTRAINT vehicle_crash_fk    FOREIGN KEY (year, st_case) REFERENCES crash (year, st_case) ON DELETE CASCADE,
    CONSTRAINT vehicle_veh_no_ck   CHECK (veh_no BETWEEN 1 AND 999),             -- 0 is reserved for people outside vehicles
    CONSTRAINT vehicle_body_typ_ck CHECK (body_typ BETWEEN 1 AND 99),
    CONSTRAINT vehicle_vspd_lim_ck CHECK (vspd_lim BETWEEN 0 AND 95 OR vspd_lim IN (98, 99)),
    CONSTRAINT vehicle_hit_run_ck  CHECK (hit_run IN (0, 1, 9))
);

CREATE TABLE pedestrian (
    year     smallint NOT NULL,
    st_case  integer  NOT NULL,
    veh_no   smallint NOT NULL,
    per_no   smallint NOT NULL,
    str_veh  smallint,
    per_typ  smallint NOT NULL,
    inj_sev  smallint NOT NULL,
    age      smallint NOT NULL,
    sex      smallint NOT NULL,
    drinking smallint NOT NULL,
    CONSTRAINT pedestrian_pk       PRIMARY KEY (year, st_case, veh_no, per_no),
    CONSTRAINT pedestrian_crash_fk FOREIGN KEY (year, st_case) REFERENCES crash (year, st_case) ON DELETE CASCADE,
    -- business rules 1 and 2: the striking vehicle must sit in the same crash of the same year
    CONSTRAINT pedestrian_striking_vehicle_fk FOREIGN KEY (year, st_case, str_veh)
        REFERENCES vehicle (year, st_case, veh_no),
    CONSTRAINT pedestrian_veh_no_ck   CHECK (veh_no = 0),                        -- people outside vehicles
    CONSTRAINT pedestrian_per_no_ck   CHECK (per_no BETWEEN 1 AND 999),
    CONSTRAINT pedestrian_str_veh_ck  CHECK (str_veh BETWEEN 1 AND 999),         -- "no link" is NULL, never 0
    CONSTRAINT pedestrian_per_typ_ck  CHECK (per_typ = 5),                       -- scope: pedestrians only
    CONSTRAINT pedestrian_inj_sev_ck  CHECK (inj_sev = 4),                       -- scope: fatal injuries only
    CONSTRAINT pedestrian_age_ck      CHECK (age BETWEEN 0 AND 120 OR age IN (998, 999)),
    CONSTRAINT pedestrian_sex_ck      CHECK (sex IN (1, 2, 8, 9)),
    CONSTRAINT pedestrian_drinking_ck CHECK (drinking IN (0, 1, 8, 9))
);

CREATE TABLE ped_crash_type (
    year     smallint NOT NULL,
    st_case  integer  NOT NULL,
    veh_no   smallint NOT NULL,
    per_no   smallint NOT NULL,
    pbcwalk  smallint NOT NULL,
    pbswalk  smallint NOT NULL,
    pedloc   smallint NOT NULL,
    pedpos   smallint NOT NULL,
    pedctype smallint NOT NULL,
    CONSTRAINT ped_crash_type_pk            PRIMARY KEY (year, st_case, veh_no, per_no),   -- same key = at most one row per pedestrian
    CONSTRAINT ped_crash_type_pedestrian_fk FOREIGN KEY (year, st_case, veh_no, per_no)
        REFERENCES pedestrian (year, st_case, veh_no, per_no) ON DELETE CASCADE,
    CONSTRAINT ped_crash_type_pbcat_fk      FOREIGN KEY (pedctype) REFERENCES pbcat_type (pedctype),
    CONSTRAINT ped_crash_type_pbcwalk_ck    CHECK (pbcwalk IN (0, 1, 9)),
    CONSTRAINT ped_crash_type_pbswalk_ck    CHECK (pbswalk IN (0, 1, 9)),
    CONSTRAINT ped_crash_type_pedloc_ck     CHECK (pedloc IN (1, 2, 3, 4, 9)),   -- 7 "not a pedestrian" cannot occur here
    CONSTRAINT ped_crash_type_pedpos_ck     CHECK (pedpos BETWEEN 1 AND 9)       -- 77 "not a pedestrian" cannot occur here
);

-- ---------------------------------------------------------------------
-- Pipeline bookkeeping (from the proposal: manifest, etl_log, validation_result)
-- ---------------------------------------------------------------------

CREATE TABLE etl_run (
    run_id      integer     GENERATED ALWAYS AS IDENTITY,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    git_commit  text,
    status      text        NOT NULL DEFAULT 'running',
    CONSTRAINT etl_run_pk         PRIMARY KEY (run_id),
    CONSTRAINT etl_run_status_ck  CHECK (status IN ('running', 'succeeded', 'failed')),
    CONSTRAINT etl_run_commit_ck  CHECK (git_commit ~ '^[0-9a-f]{7,40}$'),
    CONSTRAINT etl_run_finish_ck  CHECK ((status = 'running') = (finished_at IS NULL)),
    CONSTRAINT etl_run_order_ck   CHECK (finished_at >= started_at)
);

CREATE TABLE source_file (
    file_id      integer  GENERATED ALWAYS AS IDENTITY,
    run_id       integer  NOT NULL,
    source       text     NOT NULL,
    data_year    smallint,
    release      text     NOT NULL,
    file_name    text     NOT NULL,
    url          text     NOT NULL,
    sha256       text     NOT NULL,
    retrieved_on date     NOT NULL,
    CONSTRAINT source_file_pk        PRIMARY KEY (file_id),
    CONSTRAINT source_file_run_fk    FOREIGN KEY (run_id) REFERENCES etl_run (run_id) ON DELETE CASCADE,
    CONSTRAINT source_file_name_uq   UNIQUE (run_id, file_name),
    CONSTRAINT source_file_source_ck CHECK (source IN ('FARS', 'EPA_SLD', 'CENSUS_POPEST')),
    -- FARS files are yearly; the EPA and Census files are not
    CONSTRAINT source_file_year_ck   CHECK ((source = 'FARS') = (data_year IS NOT NULL) AND data_year BETWEEN 2020 AND 2024),
    CONSTRAINT source_file_url_ck    CHECK (url ~ '^https://'),
    CONSTRAINT source_file_sha256_ck CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE etl_log (
    log_id    integer     GENERATED ALWAYS AS IDENTITY,
    run_id    integer     NOT NULL,
    step      text        NOT NULL,
    rows_in   integer,
    rows_out  integer,
    status    text        NOT NULL,
    message   text,
    logged_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT etl_log_pk        PRIMARY KEY (log_id),
    CONSTRAINT etl_log_run_fk    FOREIGN KEY (run_id) REFERENCES etl_run (run_id) ON DELETE CASCADE,
    CONSTRAINT etl_log_status_ck CHECK (status IN ('ok', 'warning', 'error')),
    CONSTRAINT etl_log_rows_ck   CHECK (rows_in >= 0 AND rows_out >= 0)
);

CREATE TABLE validation_result (
    result_id  integer     GENERATED ALWAYS AS IDENTITY,
    run_id     integer     NOT NULL,
    check_name text        NOT NULL,
    passed     boolean     NOT NULL,
    detail     text,
    checked_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT validation_result_pk      PRIMARY KEY (result_id),
    CONSTRAINT validation_result_run_fk  FOREIGN KEY (run_id) REFERENCES etl_run (run_id) ON DELETE CASCADE,
    CONSTRAINT validation_result_name_uq UNIQUE (run_id, check_name)
);

-- Week 7: records that failed a record-level gate. The pipeline writes them in their
-- own committed transaction, so the evidence survives the rollback of the load.
-- raw_record holds the source values as read (person-level data: stays local).
CREATE TABLE rejected_record (
    reject_id     integer     GENERATED ALWAYS AS IDENTITY,
    run_id        integer     NOT NULL,
    data_year     smallint,
    file_name     text        NOT NULL,
    member        text        NOT NULL,
    source_line   integer,
    target_table  text        NOT NULL,
    record_key    text        NOT NULL,
    check_name    text        NOT NULL,
    column_name   text,
    failure_value text,
    raw_record    jsonb       NOT NULL,
    rejected_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT rejected_record_pk        PRIMARY KEY (reject_id),
    CONSTRAINT rejected_record_run_fk    FOREIGN KEY (run_id) REFERENCES etl_run (run_id) ON DELETE CASCADE,
    CONSTRAINT rejected_record_year_ck   CHECK (data_year BETWEEN 2020 AND 2024),
    CONSTRAINT rejected_record_line_ck   CHECK (source_line >= 2),               -- line 1 is the CSV header
    CONSTRAINT rejected_record_target_ck CHECK (target_table IN ('accident', 'vehicle', 'person', 'pbtype',
                                                                 'crash', 'pedestrian', 'ped_crash_type', 'county_population'))
);

-- ---------------------------------------------------------------------
-- The data dictionary lives in the database too (loaded from docs/data_dictionary.csv).
-- v_dq_undocumented_columns compares it with the catalog, so it cannot go stale quietly.
-- ---------------------------------------------------------------------

CREATE TABLE data_dictionary (
    table_name       text NOT NULL,
    column_name      text NOT NULL,
    definition       text NOT NULL,
    source           text NOT NULL,
    allowable_values text NOT NULL,
    null_meaning     text NOT NULL,
    sensitivity      text NOT NULL,
    CONSTRAINT data_dictionary_pk             PRIMARY KEY (table_name, column_name),
    CONSTRAINT data_dictionary_sensitivity_ck CHECK (sensitivity ~ '^(Public|Internal|Restricted)'),
    CONSTRAINT data_dictionary_filled_ck      CHECK (definition <> '' AND source <> '' AND allowable_values <> '' AND null_meaning <> '')
);
