-- =====================================================================
-- tests/verify_cleaning_rules.sql
-- Post-load verification tests for the five cleaning rules of
-- docs/Week6_Data_Cleaning_Plan_Shkirpan.md (section 4).
--
-- Run after the Week 7 load:
--     psql -d ped_safety -f tests/verify_cleaning_rules.sql
--
-- Expected values are the numbers measured on the raw files downloaded on
-- 2026-09-27 (docs/profile/*.csv). They are psql variables, so a reload with the
-- 2024 Final file changes the expectations in one place, on the command line:
--     psql -d ped_safety -v exp_ped_2024=700 -f tests/verify_cleaning_rules.sql
-- Every row of the output says PASS or FAIL; the last query counts the FAILs.
-- Against the Week 5 synthetic fixture (16 deaths) the count tests FAIL by design;
-- the structural tests (no NULL codes, no unknown antecedent, county digits) PASS.
-- =====================================================================
\set ON_ERROR_STOP on
\pset footer off

\if :{?exp_ped_total}   \else \set exp_ped_total   3736 \endif
\if :{?exp_crash_total} \else \set exp_crash_total 3690 \endif
\if :{?exp_ped_2020}    \else \set exp_ped_2020    695  \endif
\if :{?exp_ped_2021}    \else \set exp_ped_2021    819  \endif
\if :{?exp_ped_2022}    \else \set exp_ped_2022    780  \endif
\if :{?exp_ped_2023}    \else \set exp_ped_2023    774  \endif
\if :{?exp_ped_2024}    \else \set exp_ped_2024    668  \endif
\if :{?exp_view_total}  \else \set exp_view_total  3053 \endif
\if :{?exp_multi_crash} \else \set exp_multi_crash 42   \endif
\if :{?exp_no_point}    \else \set exp_no_point    3    \endif
\if :{?exp_spd_unknown} \else \set exp_spd_unknown 208  \endif
\if :{?exp_body_unk_hr} \else \set exp_body_unk_hr 400  \endif

DROP TABLE IF EXISTS pg_temp.result;
CREATE TEMP TABLE result (issue text, test text, expected text, actual text, pass boolean);

-- ---------------------------------------------------------------------
-- Issue 1: coded unknowns kept as values, visible as items, never antecedents
-- ---------------------------------------------------------------------
INSERT INTO result
SELECT '1 unknowns', 'no NULL in coded columns of crash/vehicle/pedestrian/ped_crash_type', '0', n::text, n = 0
FROM (SELECT (SELECT count(*) FROM crash    WHERE hour IS NULL OR rur_urb IS NULL OR func_sys IS NULL OR lgt_cond IS NULL OR reljct2 IS NULL)
           + (SELECT count(*) FROM vehicle  WHERE body_typ IS NULL OR vspd_lim IS NULL OR hit_run IS NULL)
           + (SELECT count(*) FROM pedestrian WHERE age IS NULL OR sex IS NULL OR drinking IS NULL)
           + (SELECT count(*) FROM ped_crash_type WHERE pedloc IS NULL OR pedpos IS NULL OR pbcwalk IS NULL) AS n) s;

INSERT INTO result
SELECT '1 unknowns', 'speed=unknown items in the view equal raw VSPD_LIM 98/99 count (deaths, all years)',
       :'exp_spd_unknown', n::text, n = :exp_spd_unknown
FROM (SELECT count(*) AS n
      FROM pedestrian p JOIN vehicle v ON (v.year, v.st_case, v.veh_no) = (p.year, p.st_case, p.str_veh)
      WHERE v.vspd_lim IN (98, 99)) s;

INSERT INTO result
SELECT '1 unknowns', 'BODY_TYP unknown among hit-and-run deaths reproduces the profile', :'exp_body_unk_hr', n::text, n = :exp_body_unk_hr
FROM (SELECT count(*) AS n
      FROM pedestrian p JOIN vehicle v ON (v.year, v.st_case, v.veh_no) = (p.year, p.st_case, p.str_veh)
      WHERE v.hit_run = 1 AND v.body_typ IN (98, 99)) s;

INSERT INTO result
SELECT '1 unknowns', 'every death is in the view or excluded only by the scope filter (never by an unknown item)',
       '0', n::text, n = 0
FROM (SELECT count(*) AS n
      FROM pedestrian p JOIN crash c USING (year, st_case)
      WHERE c.rur_urb = 2 AND c.func_sys BETWEEN 3 AND 7
        AND NOT EXISTS (SELECT 1 FROM v_ped_transactions t
                        WHERE (t.year, t.st_case, t.per_no) = (p.year, p.st_case, p.per_no))) s;

-- ---------------------------------------------------------------------
-- Issue 2: provisional 2024 file is tagged and reloads replace, not append
-- ---------------------------------------------------------------------
INSERT INTO result
SELECT '2 ARF', 'latest run has one source_file row per FARS year 2020-2024', '5', n::text, n = 5
FROM (SELECT count(DISTINCT data_year) AS n FROM source_file
      WHERE source = 'FARS' AND run_id = (SELECT max(run_id) FROM etl_run WHERE status = 'succeeded')) s;

INSERT INTO result
SELECT '2 ARF', '2024 file is labelled Annual Report File (until the Final file is loaded)', 'Annual Report File', coalesce(r, '(none)'), r = 'Annual Report File'
FROM (SELECT max(release) AS r FROM source_file
      WHERE source = 'FARS' AND data_year = 2024 AND run_id = (SELECT max(run_id) FROM etl_run WHERE status = 'succeeded')) s;

INSERT INTO result
SELECT '2 ARF', 'pedestrian count ' || y, exp::text, coalesce(n, 0)::text, coalesce(n, 0) = exp
FROM (VALUES (2020, :exp_ped_2020), (2021, :exp_ped_2021), (2022, :exp_ped_2022), (2023, :exp_ped_2023), (2024, :exp_ped_2024)) e(y, exp)
LEFT JOIN (SELECT year, count(*) AS n FROM pedestrian GROUP BY year) k ON k.year = e.y;

-- ---------------------------------------------------------------------
-- Issue 3: identity across years, multi-victim crashes, no deduplication
-- ---------------------------------------------------------------------
INSERT INTO result
SELECT '3 identity', 'pedestrian rows = expected total', :'exp_ped_total', n::text, n = :exp_ped_total FROM (SELECT count(*) AS n FROM pedestrian) s;
INSERT INTO result
SELECT '3 identity', 'crash rows = expected total', :'exp_crash_total', n::text, n = :exp_crash_total FROM (SELECT count(*) AS n FROM crash) s;
INSERT INTO result
SELECT '3 identity', 'crashes with 2+ pedestrian deaths', :'exp_multi_crash', n::text, n = :exp_multi_crash
FROM (SELECT count(*) AS n FROM (SELECT year, st_case FROM pedestrian GROUP BY 1, 2 HAVING count(*) >= 2) m) s;
INSERT INTO result
SELECT '3 identity', 'no crash has more pedestrian rows than FATALS', '0', n::text, n = 0
FROM (SELECT count(*) AS n FROM crash c
      WHERE fatals < (SELECT count(*) FROM pedestrian p WHERE (p.year, p.st_case) = (c.year, c.st_case))) s;
INSERT INTO result
SELECT '3 identity', 'every crash has >= 1 pedestrian and >= 1 in-transport vehicle', '0', n::text, n = 0
FROM (SELECT count(*) AS n FROM crash c
      WHERE NOT EXISTS (SELECT 1 FROM pedestrian p WHERE (p.year, p.st_case) = (c.year, c.st_case))
         OR NOT EXISTS (SELECT 1 FROM vehicle v WHERE (v.year, v.st_case) = (c.year, c.st_case))) s;
INSERT INTO result
SELECT '3 identity', 'st_case values reused across years exist (composite key is doing work)', '> 0', n::text, n > 0
FROM (SELECT count(*) AS n FROM (SELECT st_case FROM crash GROUP BY st_case HAVING count(DISTINCT year) > 1) r) s;

-- ---------------------------------------------------------------------
-- Issue 4: code lists are total, grouped, and year-aware
-- ---------------------------------------------------------------------
INSERT INTO result
SELECT '4 codes', 'no observed code without a label valid for its year (v_dq_unlabeled_code)', '0', n::text, n = 0
FROM (SELECT count(*) AS n FROM v_dq_unlabeled_code) s;
INSERT INTO result
SELECT '4 codes', 'no NULL item in the transaction view', '0', n::text, n = 0
FROM (SELECT count(*) AS n FROM v_ped_transactions
      WHERE road_class IS NULL OR speed_bin IS NULL OR light IS NULL OR crossing_location IS NULL
         OR crosswalk IS NULL OR time_of_day IS NULL OR junction IS NULL OR crash_group IS NULL
         OR vehicle_class IS NULL OR hit_and_run IS NULL OR age_group IS NULL OR walkability IS NULL) s;
INSERT INTO result
SELECT '4 codes', 'view rows = expected analysis population', :'exp_view_total', n::text, n = :exp_view_total
FROM (SELECT count(*) AS n FROM v_ped_transactions) s;
INSERT INTO result
SELECT '4 codes', 'no view row outside the scope (urban, FUNC_SYS 3-7)', '0', n::text, n = 0
FROM (SELECT count(*) AS n FROM v_ped_transactions t JOIN crash c USING (year, st_case)
      WHERE c.rur_urb <> 2 OR c.func_sys NOT BETWEEN 3 AND 7) s;

-- ---------------------------------------------------------------------
-- Issue 5: geography
-- ---------------------------------------------------------------------
INSERT INTO result
SELECT '5 geography', 'crashes without a usable point', :'exp_no_point', n::text, n = :exp_no_point
FROM (SELECT count(*) AS n FROM crash WHERE latitude IS NULL) s;
INSERT INTO result
SELECT '5 geography', 'block-group county digits agree with the crash county (v_dq_county_block_group_mismatch)', '0', n::text, n = 0
FROM (SELECT count(*) AS n FROM v_dq_county_block_group_mismatch) s;
INSERT INTO result
SELECT '5 geography', 'share of crashes with a block group (target >= 90%)', '>= 90',
       coalesce(round(100.0 * with_bg / nullif(total, 0), 1)::text, 'n/a'),
       coalesce(100.0 * with_bg / nullif(total, 0) >= 90, false)
FROM (SELECT count(*) AS total, count(geoid10) AS with_bg FROM crash) s;
INSERT INTO result
SELECT '5 geography', 'county rates cover every death (sum over v_county_rate = pedestrian rows)', (SELECT count(*) FROM pedestrian)::text, n::text, n = (SELECT count(*) FROM pedestrian)
FROM (SELECT coalesce(sum(deaths_all), 0) AS n FROM v_county_rate) s;
INSERT INTO result
SELECT '5 geography', 'no negative transit distance (EPA sentinel -99999 must be NULL)', '0', n::text, n = 0
FROM (SELECT count(*) AS n FROM block_group WHERE d4a < 0) s;

SELECT issue, test, expected, actual, CASE WHEN pass THEN 'PASS' ELSE 'FAIL' END AS result FROM result ORDER BY issue, test;
SELECT count(*) FILTER (WHERE pass) AS passed, count(*) FILTER (WHERE NOT pass) AS failed FROM result;
