-- =====================================================================
-- tests/test_constraints.sql   do the constraints behave?
--
--   psql -d ped_safety -f tests/test_constraints.sql      (from the repository root)
--
-- Run it after the build and after tests/fixtures/valid_records.sql.
-- It prints the results and also writes them to docs/evidence/03_constraint_tests.csv.
-- Every test is one row in the temporary table test_case: the statement to send
-- and what must come back.
--   exp_state filled  the statement MUST be rejected with that SQLSTATE, and the
--                     error must name the constraint in exp_constraint. A rejection
--                     by some other rule counts as a failed test, so a test cannot
--                     pass by accident.
--   exp_state empty   the statement MUST be accepted (valid edge cases).
-- The runner at the bottom sends each statement inside its own savepoint and rolls
-- it back, and the file ends with ROLLBACK, so the database is left as it was.
-- SQLSTATE classes: 23505 unique, 23503 foreign key, 23514 check,
-- 23502 not null, 23P01 exclusion, 42501 permission denied.
-- =====================================================================
\set ON_ERROR_STOP on
\pset pager off
BEGIN;

CREATE TEMP TABLE test_result (
    test_id   text PRIMARY KEY,
    rule      text NOT NULL,
    attempt   text NOT NULL,
    expected  text NOT NULL,
    got       text NOT NULL,
    message   text,
    verdict   text NOT NULL,
    seq       integer GENERATED ALWAYS AS IDENTITY
) ON COMMIT DROP;

CREATE TEMP TABLE test_case (
    seq            integer GENERATED ALWAYS AS IDENTITY,
    test_id        text PRIMARY KEY,
    rule           text NOT NULL,       -- the rule under test, in words
    attempt        text NOT NULL,       -- what the statement tries to do
    stmt           text NOT NULL,       -- the SQL that is sent
    exp_state      text,                -- SQLSTATE that must come back; NULL = the statement must be accepted
    exp_constraint text,                -- constraint that must be named in the error (when the error names one)
    run_as         text                 -- role to switch to first (access-control tests)
) ON COMMIT DROP;

-- =====================================================================
-- A. Entity integrity (keys)
-- =====================================================================
INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'A1',
  'Rule 1: a crash is identified by year + st_case',
  'second crash with the key (2021, 120417)',
  $t$INSERT INTO crash VALUES (2021,120417,9,1,1,12,2,3,1,1,1,NULL,NULL,NULL,'TEST RD',1,1)$t$,
  '23505', 'crash_pk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, run_as) VALUES (
  'A2',
  'Rule 1: st_case is reused every year',
  'crash (2022, 120417): same st_case as R1 and R2, new year, with its vehicle and pedestrian',
  $t$INSERT INTO crash VALUES (2022,120417,9,1,1,12,2,3,1,1,1,NULL,NULL,NULL,'TEST RD',1,1);
    INSERT INTO vehicle VALUES (2022,120417,1,4,45,0);
    INSERT INTO pedestrian VALUES (2022,120417,0,1,1,5,4,40,1,0)$t$,
  NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'A3',
  'a pedestrian is identified inside the crash by per_no',
  'second pedestrian row with the key (2024, 120078, 0, 1)',
  $t$INSERT INTO pedestrian VALUES (2024,120078,0,1,1,5,4,50,1,0)$t$,
  '23505', 'pedestrian_pk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'A4',
  'key columns are never empty',
  'pedestrian with per_no NULL',
  $t$INSERT INTO pedestrian VALUES (2024,120078,0,NULL,1,5,4,50,1,0)$t$,
  '23502', NULL, NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'A5',
  'at most one crash-typing record per pedestrian',
  'second ped_crash_type row for pedestrian (2021, 120417, 0, 1)',
  $t$INSERT INTO ped_crash_type VALUES (2021,120417,0,1,0,0,3,3,770)$t$,
  '23505', 'ped_crash_type_pk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'A6',
  'one population estimate per county and year',
  'second estimate for Brevard 2021',
  $t$INSERT INTO county_population VALUES (9,2021,617000,2025)$t$,
  '23505', 'county_population_pk', NULL);

-- =====================================================================
-- B. Referential integrity (relationships)
-- =====================================================================
INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B1',
  'Rule 1: every vehicle belongs to a crash of the same year',
  'vehicle for crash (2020, 120001), which does not exist',
  $t$INSERT INTO vehicle VALUES (2020,120001,1,4,35,0)$t$,
  '23503', 'vehicle_crash_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B2',
  'Rule 1: every pedestrian belongs to a crash of the same year',
  'pedestrian with st_case 120417 in 2020 (the case exists in 2021 and 2023 only)',
  $t$INSERT INTO pedestrian VALUES (2020,120417,0,1,NULL,5,4,40,1,0)$t$,
  '23503', 'pedestrian_crash_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B3',
  'Rule 2: the striking vehicle must be a vehicle of the same crash',
  'pedestrian 2 in crash (2022, 121307) with str_veh = 2; that crash has vehicle 1 only',
  $t$INSERT INTO pedestrian VALUES (2022,121307,0,2,2,5,4,40,1,0)$t$,
  '23503', 'pedestrian_striking_vehicle_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B4',
  'Rule 2: "no striking vehicle" is stored as NULL, never as 0',
  'pedestrian with str_veh = 0',
  $t$INSERT INTO pedestrian VALUES (2022,121307,0,2,0,5,4,40,1,0)$t$,
  '23514', 'pedestrian_str_veh_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, run_as) VALUES (
  'B5',
  'Rule 2: the striking-vehicle link is optional',
  'pedestrian with str_veh NULL',
  $t$INSERT INTO pedestrian VALUES (2022,121307,0,2,NULL,5,4,40,1,0)$t$,
  NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B6',
  'Rule 2: a vehicle that struck someone cannot be removed on its own',
  'delete vehicle (2021, 120417, 1) while its pedestrian stays',
  $t$DELETE FROM vehicle WHERE year = 2021 AND st_case = 120417 AND veh_no = 1$t$,
  '23503', 'pedestrian_striking_vehicle_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B7',
  'Rule 3: every crash has a county that exists',
  'crash with the FARS county code 999 (unknown)',
  $t$INSERT INTO crash VALUES (2023,120999,999,5,2,14,2,4,2,1,1,NULL,NULL,NULL,'TEST RD',1,1)$t$,
  '23503', 'crash_county_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B8',
  'Rule 3: a county with crashes cannot be deleted',
  'delete Brevard (9)',
  $t$DELETE FROM county WHERE county_fips = 9$t$,
  '23503', NULL, NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B9',
  'Rule 3: the block group must exist',
  'crash geocoded to block group 120099999999',
  $t$INSERT INTO crash VALUES (2023,120998,9,5,2,14,2,4,2,1,1,28.1,-80.6,'120099999999','TEST RD',1,1)$t$,
  '23503', 'crash_block_group_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B10',
  'a typing record needs its pedestrian',
  'ped_crash_type row for pedestrian (2021, 120417, 0, 7), who does not exist',
  $t$INSERT INTO ped_crash_type VALUES (2021,120417,0,7,0,0,3,3,760)$t$,
  '23503', 'ped_crash_type_pedestrian_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B11',
  'the crash type must be a PBCAT pedestrian type',
  'typing record for Q7 with pedctype 0 ("not a pedestrian")',
  $t$INSERT INTO ped_crash_type VALUES (2023,120052,0,1,0,0,3,3,0)$t$,
  '23503', 'ped_crash_type_pbcat_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B12',
  'a block group lies in a county that exists',
  'block group 120250001001 (county 025, the retired Dade code)',
  $t$INSERT INTO block_group (geoid10, natwalkind, d3b, d4a, totpop) VALUES ('120250001001',8,10,NULL,1000)$t$,
  '23503', 'block_group_county_fk', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'B13',
  'the county of a block group comes from its GEOID and cannot be typed in',
  'insert a block group with county_fips written by hand',
  $t$INSERT INTO block_group (geoid10, county_fips, natwalkind, totpop) VALUES ('120090651999',11,8,1000)$t$,
  '428C9', NULL, NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, run_as) VALUES (
  'B14',
  'reload of one year: deleting a crash removes its vehicles, pedestrians, and typing records',
  'delete every 2024 crash (the Annual Report File is replaced by the Final file)',
  $t$DELETE FROM crash WHERE year = 2024;
    DO $do$ BEGIN
      IF EXISTS (SELECT 1 FROM vehicle WHERE year = 2024)
         OR EXISTS (SELECT 1 FROM pedestrian WHERE year = 2024)
         OR EXISTS (SELECT 1 FROM ped_crash_type WHERE year = 2024)
      THEN RAISE EXCEPTION 'children left behind'; END IF;
    END $do$ $t$,
  NULL);

-- =====================================================================
-- C. Domain integrity (allowable values)
-- =====================================================================
INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C1',
  'scope: crash years 2020-2024',
  'crash dated 2019',
  $t$INSERT INTO crash VALUES (2019,120500,9,5,2,14,2,4,2,1,1,NULL,NULL,NULL,'TEST RD',1,1)$t$,
  '23514', 'crash_year_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C2',
  'scope: Florida only (st_case starts with 12)',
  'crash with st_case 130001 (Georgia)',
  $t$INSERT INTO crash VALUES (2023,130001,9,5,2,14,2,4,2,1,1,NULL,NULL,NULL,'TEST RD',1,1)$t$,
  '23514', 'crash_st_case_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C3',
  'scope: pedestrians only (PER_TYP = 5)',
  'a bicyclist (per_typ 6) in the pedestrian table',
  $t$INSERT INTO pedestrian VALUES (2022,121307,0,2,1,6,4,40,1,0)$t$,
  '23514', 'pedestrian_per_typ_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C4',
  'scope: fatal injuries only (INJ_SEV = 4)',
  'a pedestrian with a serious injury (inj_sev 3)',
  $t$INSERT INTO pedestrian VALUES (2022,121307,0,2,1,5,3,40,1,0)$t$,
  '23514', 'pedestrian_inj_sev_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C5',
  'pedestrians are outside vehicles (VEH_NO = 0)',
  'pedestrian row with veh_no 1',
  $t$INSERT INTO pedestrian VALUES (2022,121307,1,2,1,5,4,40,1,0)$t$,
  '23514', 'pedestrian_veh_no_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C6',
  'vehicles are numbered from 1',
  'vehicle with veh_no 0',
  $t$INSERT INTO vehicle VALUES (2022,121307,0,4,40,0)$t$,
  '23514', 'vehicle_veh_no_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C7',
  'LGT_COND codes are 1-9',
  'crash with lgt_cond 0',
  $t$INSERT INTO crash VALUES (2023,120997,9,5,2,14,2,4,2,0,1,NULL,NULL,NULL,'TEST RD',1,1)$t$,
  '23514', 'crash_lgt_cond_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C8',
  'HOUR is 0-23, or 99 for unknown',
  'crash at hour 24',
  $t$INSERT INTO crash VALUES (2023,120997,9,5,2,24,2,4,2,1,1,NULL,NULL,NULL,'TEST RD',1,1)$t$,
  '23514', 'crash_hour_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C9',
  'FUNC_SYS codes are 1-7, 96, 98, 99',
  'crash with func_sys 8',
  $t$INSERT INTO crash VALUES (2023,120997,9,5,2,14,2,8,2,1,1,NULL,NULL,NULL,'TEST RD',1,1)$t$,
  '23514', 'crash_func_sys_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C10',
  'posted speed limit is 0-95 mph, or 98/99',
  'vehicle with vspd_lim 97',
  $t$INSERT INTO vehicle VALUES (2022,121307,2,4,97,0)$t$,
  '23514', 'vehicle_vspd_lim_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C11',
  'AGE is 0-120, or 998/999',
  'pedestrian aged 130',
  $t$INSERT INTO pedestrian VALUES (2022,121307,0,2,1,5,4,130,1,0)$t$,
  '23514', 'pedestrian_age_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C12',
  'SEX codes are 1, 2, 8, 9',
  'pedestrian with sex 3 (a code NHTSA withdrew from the 2022 file)',
  $t$INSERT INTO pedestrian VALUES (2022,121307,0,2,1,5,4,40,3,0)$t$,
  '23514', 'pedestrian_sex_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C13',
  'PEDLOC 7 means "not a pedestrian" and cannot occur here',
  'typing record for Q7 with pedloc 7',
  $t$INSERT INTO ped_crash_type VALUES (2023,120052,0,1,0,0,7,3,760)$t$,
  '23514', 'ped_crash_type_pedloc_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, run_as) VALUES (
  'C14',
  'unknown codes are values, not errors',
  'crash with hour 99, lgt_cond 9, func_sys 99; vehicle with vspd_lim 99 and body_typ 99; pedestrian with age 998, sex 9, drinking 8',
  $t$INSERT INTO crash VALUES (2023,120996,9,5,2,99,2,99,99,9,99,NULL,NULL,NULL,NULL,1,1);
    INSERT INTO vehicle VALUES (2023,120996,1,99,99,9);
    INSERT INTO pedestrian VALUES (2023,120996,0,1,1,5,4,998,9,8)$t$,
  NULL);

-- coordinates and block group (Rule 3)
INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C15',
  'Rule 3: the FARS filler 77.7777 is not a latitude; it must arrive as NULL',
  'crash with latitude 77.7777 and longitude 777.7777',
  $t$INSERT INTO crash VALUES (2023,120995,9,5,2,14,2,4,2,1,1,77.7777,777.7777,NULL,'TEST RD',1,1)$t$,
  '23514', NULL, NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C16',
  'Rule 3: a point has both coordinates or neither',
  'crash with a latitude and no longitude',
  $t$INSERT INTO crash VALUES (2023,120995,9,5,2,14,2,4,2,1,1,28.1,NULL,NULL,'TEST RD',1,1)$t$,
  '23514', 'crash_point_both_or_neither_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C17',
  'Rule 3: a point must fall inside Florida''s bounding box',
  'crash at 40.7128, -74.0060 (New York)',
  $t$INSERT INTO crash VALUES (2023,120995,9,5,2,14,2,4,2,1,1,40.7128,-74.0060,NULL,'TEST RD',1,1)$t$,
  '23514', NULL, NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C18',
  'Rule 3: no block group without valid coordinates',
  'crash with a block group and NULL coordinates',
  $t$INSERT INTO crash VALUES (2023,120995,9,5,2,14,2,4,2,1,1,NULL,NULL,'120090651021','TEST RD',1,1)$t$,
  '23514', 'crash_block_group_needs_point_ck', NULL);

-- reference data
INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C19',
  'the walkability index runs from 1 to 20',
  'block group with natwalkind 21.5',
  $t$INSERT INTO block_group (geoid10, natwalkind, totpop) VALUES ('120090651998',21.5,1000)$t$,
  '23514', 'block_group_natwalkind_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C20',
  'EPA''s -99999 (no transit stop nearby) must arrive as NULL',
  'block group with d4a = -99999',
  $t$INSERT INTO block_group (geoid10, natwalkind, d4a, totpop) VALUES ('120090651998',8,-99999,1000)$t$,
  '23514', 'block_group_d4a_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C21',
  'a block-group GEOID is 12 digits and starts with 12 (Florida)',
  'block group 130510001001 (Georgia)',
  $t$INSERT INTO block_group (geoid10, natwalkind, totpop) VALUES ('130510001001',8,1000)$t$,
  '23514', 'block_group_geoid_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C22',
  'a population estimate is a positive number',
  'Lafayette 2021 with population 0',
  $t$UPDATE county_population SET population = 0 WHERE county_fips = 67 AND year = 2021$t$,
  '23514', 'county_population_pop_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C23',
  'an estimate for year Y cannot come from a vintage before Y',
  'a 2024 estimate labelled Vintage 2023',
  $t$UPDATE county_population SET vintage = 2023 WHERE county_fips = 67 AND year = 2024$t$,
  '23514', 'county_population_vintage_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C24',
  'one code has one label in any given year',
  'second label for lgt_cond 2 valid 2022-2024 (the first covers 2020-2024)',
  $t$INSERT INTO code_lookup (variable, code, year_from, year_to, label) VALUES ('lgt_cond',2,2022,2024,'Dark')$t$,
  '23P01', 'code_lookup_no_overlap_ex', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C25',
  'a file in the manifest carries a real SHA-256 checksum',
  'source_file row with sha256 = ''abc''',
  $t$INSERT INTO source_file (run_id, source, data_year, release, file_name, url, sha256, retrieved_on)
    SELECT run_id,'FARS',2023,'Final','x.zip','https://static.nhtsa.gov/x.zip','abc',DATE '2026-09-08' FROM etl_run LIMIT 1$t$,
  '23514', 'source_file_sha256_ck', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'C26',
  'a finished run has a finish time, a running one does not',
  'etl_run marked succeeded with finished_at NULL',
  $t$INSERT INTO etl_run (status) VALUES ('succeeded')$t$,
  '23514', 'etl_run_finish_ck', NULL);

-- =====================================================================
-- D. Cardinality: the "one or more" ends (checked at COMMIT)
-- =====================================================================
INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'D1',
  'a crash kills one or more pedestrians',
  'crash and vehicle, but no pedestrian row',
  $t$INSERT INTO crash VALUES (2023,120994,9,5,2,14,2,4,2,1,1,NULL,NULL,NULL,'TEST RD',1,1);
    INSERT INTO vehicle VALUES (2023,120994,1,4,35,0)$t$,
  '23514', 'crash_min_one_pedestrian', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'D2',
  'a crash involves one or more vehicles in transport',
  'crash and pedestrian, but no vehicle row',
  $t$INSERT INTO crash VALUES (2023,120994,9,5,2,14,2,4,2,1,1,NULL,NULL,NULL,'TEST RD',1,1);
    INSERT INTO pedestrian VALUES (2023,120994,0,1,NULL,5,4,40,1,0)$t$,
  '23514', 'crash_min_one_vehicle', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'D3',
  'a crash kills one or more pedestrians (also after a delete)',
  'delete the only pedestrian of crash (2021, 120417)',
  $t$DELETE FROM pedestrian WHERE year = 2021 AND st_case = 120417$t$,
  '23514', 'crash_min_one_pedestrian', NULL);

INSERT INTO test_case (test_id, rule, attempt, stmt, run_as) VALUES (
  'D4',
  'E1: one crash may kill several pedestrians',
  'delete one of the two pedestrians of crash (2024, 120078); one is left, so the crash is still valid',
  $t$DELETE FROM pedestrian WHERE year = 2024 AND st_case = 120078 AND per_no = 2$t$,
  NULL);

-- =====================================================================
-- E. Access control (sensitivity rules as permissions)
-- =====================================================================
INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'E1',
  'the dashboard role cannot read person-level rows',
  'ped_dashboard: SELECT * FROM pedestrian',
  $t$SELECT * FROM pedestrian$t$,
  '42501', NULL, 'ped_dashboard');

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'E2',
  'the dashboard role cannot read crash coordinates',
  'ped_dashboard: SELECT latitude, longitud FROM crash',
  $t$SELECT latitude, longitud FROM crash$t$,
  '42501', NULL, 'ped_dashboard');

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'E3',
  'the dashboard role cannot read the case-level analysis view',
  'ped_dashboard: SELECT * FROM v_ped_transactions',
  $t$SELECT * FROM v_ped_transactions$t$,
  '42501', NULL, 'ped_dashboard');

INSERT INTO test_case (test_id, rule, attempt, stmt, run_as) VALUES (
  'E4',
  'the dashboard role can read aggregates',
  'ped_dashboard: SELECT from v_county_rate and v_dash_pattern_county',
  $t$SELECT * FROM v_county_rate; SELECT * FROM v_dash_pattern_county$t$,
  'ped_dashboard');

INSERT INTO test_case (test_id, rule, attempt, stmt, exp_state, exp_constraint, run_as) VALUES (
  'E5',
  'the analyst role reads everything but changes nothing',
  'ped_analyst: UPDATE crash SET lgt_cond = 1',
  $t$UPDATE crash SET lgt_cond = 1$t$,
  '42501', NULL, 'ped_analyst');

INSERT INTO test_case (test_id, rule, attempt, stmt, run_as) VALUES (
  'E6',
  'the analyst role can read the analysis view',
  'ped_analyst: SELECT * FROM v_ped_transactions',
  $t$SELECT * FROM v_ped_transactions$t$,
  'ped_analyst');

-- =====================================================================
-- Runner: send every statement, catch what comes back, undo it, log the verdict
-- =====================================================================
DO $run$
DECLARE
    t record;
    v_state text; v_constraint text; v_msg text;
BEGIN
    FOR t IN SELECT * FROM test_case ORDER BY seq LOOP
        v_state := NULL; v_constraint := NULL; v_msg := NULL;
        BEGIN                                        -- a savepoint: whatever happens inside is undone
            IF t.run_as IS NOT NULL THEN EXECUTE format('SET LOCAL ROLE %I', t.run_as); END IF;
            EXECUTE t.stmt;
            SET CONSTRAINTS ALL IMMEDIATE;           -- fire the commit-time rules now
            RAISE EXCEPTION USING ERRCODE = 'ZZ001', MESSAGE = 'accepted';
        EXCEPTION WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS v_state = RETURNED_SQLSTATE, v_constraint = CONSTRAINT_NAME, v_msg = MESSAGE_TEXT;
        END;
        RESET ROLE;
        SET CONSTRAINTS ALL DEFERRED;

        INSERT INTO test_result (test_id, rule, attempt, expected, got, message, verdict)
        VALUES (t.test_id, t.rule, t.attempt,
                CASE WHEN t.exp_state IS NULL THEN 'ACCEPT'
                     ELSE 'REJECT ' || t.exp_state || COALESCE(' ' || t.exp_constraint, '') END,
                CASE WHEN v_state = 'ZZ001' THEN 'ACCEPTED'
                     ELSE 'REJECTED ' || v_state || COALESCE(' ' || NULLIF(v_constraint, ''), '') END,
                CASE WHEN v_state = 'ZZ001' THEN NULL ELSE v_msg END,
                CASE WHEN t.exp_state IS NULL AND v_state = 'ZZ001' THEN 'PASS'
                     WHEN t.exp_state = v_state AND (t.exp_constraint IS NULL OR t.exp_constraint = v_constraint) THEN 'PASS'
                     ELSE 'FAIL' END);
    END LOOP;
END;
$run$;

-- =====================================================================
-- Results
-- =====================================================================
\echo
\echo ===== Results: one line per test (expected vs. what PostgreSQL did) =====
SELECT test_id AS id, rule, expected, got, verdict
FROM test_result ORDER BY seq;

\echo ===== What each test tried, and the error text PostgreSQL returned =====
\pset format unaligned
\pset tuples_only on
SELECT test_id || '  ' || attempt || E'\n      -> ' || COALESCE(message, 'accepted')
FROM test_result ORDER BY seq;
\pset tuples_only off
\pset format aligned
-- the same results as a file, for the design document
\copy (SELECT test_id, rule, attempt, expected, got, COALESCE(message, '') AS postgresql_message, verdict FROM test_result ORDER BY seq) TO 'docs/evidence/03_constraint_tests.csv' WITH (FORMAT csv, HEADER true)

\echo ===== Summary =====
SELECT count(*) AS tests,
       count(*) FILTER (WHERE verdict = 'PASS') AS passed,
       count(*) FILTER (WHERE verdict = 'FAIL') AS failed,
       count(*) FILTER (WHERE expected LIKE 'REJECT%') AS invalid_records_tried,
       count(*) FILTER (WHERE expected = 'ACCEPT')     AS valid_edge_cases_tried
FROM test_result;

-- Stop with an error (non-zero exit code) if any test failed.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM test_result WHERE verdict = 'FAIL') THEN
        RAISE EXCEPTION 'constraint tests failed';
    END IF;
END;
$$;

\echo ===== The fixture is untouched (everything above was rolled back) =====
SELECT (SELECT count(*) FROM crash) AS crashes, (SELECT count(*) FROM vehicle) AS vehicles,
       (SELECT count(*) FROM pedestrian) AS pedestrians, (SELECT count(*) FROM ped_crash_type) AS typing_records;

ROLLBACK;
