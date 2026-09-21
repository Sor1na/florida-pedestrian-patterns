-- =====================================================================
-- 04_views.sql
--   v_ped_transactions     one row per in-scope pedestrian death, codes turned into items
--   v_county_rate          five-year county fatality rates (Objective 3)
--   v_dash_pattern_county  aggregated pattern counts per county (what the dashboard reads)
--   v_dq_*                 data-quality checks the pipeline reads after every load
-- The base tables keep FARS codes exactly as published. All binning and labelling
-- happens here, so changing a bin edge never touches stored data.
-- =====================================================================

-- ---------------------------------------------------------------------
-- The analysis view. Scope filter from the proposal: urban (RUR_URB = 2),
-- interstates and other freeways left out (FUNC_SYS 1-2).
-- LEFT JOINs on purpose: a death with no striking-vehicle link, no typing
-- record, or no block group stays in, and the missing items read 'unknown'.
-- ---------------------------------------------------------------------
CREATE VIEW v_ped_transactions AS
SELECT
    p.year,
    p.st_case,
    p.per_no,
    c.county              AS county_fips,
    co.name               AS county_name,
    CASE c.func_sys
        WHEN 3 THEN 'principal arterial'
        WHEN 4 THEN 'minor arterial'
        WHEN 5 THEN 'collector'
        WHEN 6 THEN 'collector'
        WHEN 7 THEN 'local road'
        ELSE 'unknown'
    END                   AS road_class,
    CASE
        WHEN v.vspd_lim IS NULL OR v.vspd_lim IN (98, 99) THEN 'unknown'
        WHEN v.vspd_lim = 0   THEN 'no statutory limit'
        WHEN v.vspd_lim <= 30 THEN '30 mph or less'
        WHEN v.vspd_lim <= 40 THEN '35-40 mph'
        WHEN v.vspd_lim <= 50 THEN '45-50 mph'
        ELSE '55 mph or more'
    END                   AS speed_bin,
    CASE c.lgt_cond
        WHEN 1 THEN 'daylight'
        WHEN 2 THEN 'dark, not lighted'
        WHEN 3 THEN 'dark, lighted'
        WHEN 4 THEN 'dawn or dusk'
        WHEN 5 THEN 'dawn or dusk'
        WHEN 6 THEN 'dark, lighting unknown'
        ELSE 'unknown'
    END                   AS light,
    CASE t.pedloc
        WHEN 1 THEN 'at intersection'
        WHEN 2 THEN 'intersection-related'
        WHEN 3 THEN 'not at intersection'
        WHEN 4 THEN 'non-trafficway'
        ELSE 'unknown'                        -- code 9, or no typing record
    END                   AS crossing_location,
    CASE t.pbcwalk
        WHEN 1 THEN 'marked crosswalk'
        WHEN 0 THEN 'no crosswalk noted'
        ELSE 'unknown'
    END                   AS crosswalk,
    CASE
        WHEN c.hour = 99            THEN 'unknown'
        WHEN c.hour BETWEEN 6 AND 9   THEN 'morning (6-9)'
        WHEN c.hour BETWEEN 10 AND 15 THEN 'midday (10-15)'
        WHEN c.hour BETWEEN 16 AND 19 THEN 'evening (16-19)'
        WHEN c.hour BETWEEN 20 AND 23 THEN 'night (20-23)'
        ELSE 'late night (0-5)'
    END                   AS time_of_day,
    CASE WHEN c.day_week IN (1, 7) THEN 'weekend' ELSE 'weekday' END AS day_type,
    CASE c.reljct2
        WHEN 1 THEN 'non-junction'
        WHEN 2 THEN 'intersection'
        WHEN 3 THEN 'intersection-related'
        WHEN 4 THEN 'driveway'
        WHEN 8 THEN 'driveway'
        WHEN 98 THEN 'unknown'
        WHEN 99 THEN 'unknown'
        ELSE 'other junction type'
    END                   AS junction,
    COALESCE(g.label, 'unknown') AS crash_group,
    CASE
        WHEN v.body_typ IS NULL OR v.body_typ IN (98, 99) THEN 'unknown'
        WHEN v.body_typ BETWEEN 1 AND 13 OR v.body_typ = 17 THEN 'passenger car'
        WHEN v.body_typ IN (14, 15, 16, 19) THEN 'SUV'
        WHEN v.body_typ BETWEEN 20 AND 29   THEN 'van'
        WHEN v.body_typ BETWEEN 30 AND 39   THEN 'pickup'
        WHEN v.body_typ BETWEEN 40 AND 49   THEN 'other light truck'
        WHEN v.body_typ BETWEEN 50 AND 59   THEN 'bus'
        WHEN v.body_typ BETWEEN 60 AND 79   THEN 'medium or heavy truck'
        WHEN v.body_typ BETWEEN 80 AND 89   THEN 'motorcycle'
        ELSE 'other vehicle'
    END                   AS vehicle_class,
    CASE v.hit_run WHEN 1 THEN 'hit-and-run' WHEN 0 THEN 'driver stayed' ELSE 'unknown' END AS hit_and_run,
    CASE
        WHEN p.age IN (998, 999) THEN 'unknown'
        WHEN p.age < 18 THEN 'under 18'
        WHEN p.age < 35 THEN '18-34'
        WHEN p.age < 65 THEN '35-64'
        ELSE '65 or older'
    END                   AS age_group,
    -- EPA's four walkability classes (EPA, 2021a)
    CASE
        WHEN bg.natwalkind IS NULL   THEN 'unknown'
        WHEN bg.natwalkind <= 5.75   THEN 'least walkable'
        WHEN bg.natwalkind <= 10.5   THEN 'below average'
        WHEN bg.natwalkind <= 15.25  THEN 'above average'
        ELSE 'most walkable'
    END                   AS walkability,
    -- stratifier only (proposal, section 10): never used as a rule antecedent
    CASE p.drinking WHEN 1 THEN 'alcohol reported' WHEN 0 THEN 'no alcohol reported' ELSE 'unknown' END AS alcohol_stratum
FROM pedestrian p
JOIN crash  c  ON c.year = p.year AND c.st_case = p.st_case
JOIN county co ON co.county_fips = c.county
LEFT JOIN vehicle v
       ON v.year = p.year AND v.st_case = p.st_case AND v.veh_no = p.str_veh
LEFT JOIN ped_crash_type t
       ON t.year = p.year AND t.st_case = p.st_case AND t.veh_no = p.veh_no AND t.per_no = p.per_no
LEFT JOIN pbcat_type  pt ON pt.pedctype = t.pedctype
LEFT JOIN pbcat_group g  ON g.pedcgp = pt.pedcgp
LEFT JOIN block_group bg ON bg.geoid10 = c.geoid10
WHERE c.rur_urb = 2
  AND c.func_sys NOT IN (1, 2);

-- ---------------------------------------------------------------------
-- County rates. Starts from COUNTY, so all 67 counties appear, also those
-- with no deaths. The denominator is the sum of the yearly July 1 estimates
-- (person-years), so the rate reads "deaths per 100,000 residents per year".
-- ---------------------------------------------------------------------
CREATE VIEW v_county_rate AS
WITH deaths AS (
    SELECT c.county AS county_fips,
           count(*) AS deaths_all,
           count(*) FILTER (WHERE c.rur_urb = 2 AND c.func_sys NOT IN (1, 2)) AS deaths_in_scope
    FROM pedestrian p
    JOIN crash c ON c.year = p.year AND c.st_case = p.st_case
    GROUP BY c.county
), pop AS (
    SELECT county_fips,
           sum(population) AS person_years,
           count(*)        AS years_with_population
    FROM county_population
    GROUP BY county_fips
)
SELECT co.county_fips,
       co.name                                    AS county_name,
       COALESCE(d.deaths_all, 0)                  AS deaths_all,
       COALESCE(d.deaths_in_scope, 0)             AS deaths_in_scope,
       pop.person_years,
       COALESCE(pop.years_with_population, 0)     AS years_with_population,
       round(100000.0 * COALESCE(d.deaths_all, 0) / pop.person_years, 2) AS rate_per_100k_per_year,
       (COALESCE(d.deaths_all, 0) < 20)           AS unstable_rate      -- proposal, section 9
FROM county co
LEFT JOIN deaths d ON d.county_fips = co.county_fips
LEFT JOIN pop      ON pop.county_fips = co.county_fips;

-- ---------------------------------------------------------------------
-- What the dashboard role may read: counts per county and pattern.
-- No person attributes, no coordinates, no case numbers.
-- ---------------------------------------------------------------------
CREATE VIEW v_dash_pattern_county AS
SELECT county_fips, county_name, road_class, speed_bin, light, crossing_location, time_of_day,
       count(*) AS deaths
FROM v_ped_transactions
GROUP BY county_fips, county_name, road_class, speed_bin, light, crossing_location, time_of_day;

-- ---------------------------------------------------------------------
-- Data-quality views. Each one should return zero rows after a good load.
-- The pipeline copies the row counts into validation_result.
-- ---------------------------------------------------------------------

-- 1. FARS counts that contradict the rows loaded. FATALS counts every death in the
--    crash and PEDS counts every person outside a vehicle, so both must be at least
--    the number of pedestrian-fatality rows.
CREATE VIEW v_dq_count_mismatch AS
SELECT c.year, c.st_case, c.fatals, c.peds, count(p.per_no) AS pedestrian_rows
FROM crash c
LEFT JOIN pedestrian p ON p.year = c.year AND p.st_case = c.st_case
GROUP BY c.year, c.st_case, c.fatals, c.peds
HAVING count(p.per_no) > c.fatals OR count(p.per_no) > c.peds;

-- 2. Pedestrians with no crash-typing record (allowed, but it should be rare).
CREATE VIEW v_dq_missing_typing AS
SELECT p.year, p.st_case, p.per_no
FROM pedestrian p
LEFT JOIN ped_crash_type t
       ON t.year = p.year AND t.st_case = p.st_case AND t.veh_no = p.veh_no AND t.per_no = p.per_no
WHERE t.per_no IS NULL;

-- 3. Pedestrians with no striking-vehicle link (allowed; how many is what matters).
CREATE VIEW v_dq_no_striking_vehicle AS
SELECT year, st_case, per_no FROM pedestrian WHERE str_veh IS NULL;

-- 4. The geocoded block group lies in another county than the one FARS coded.
--    Not blocked by a constraint: either source can be the wrong one.
CREATE VIEW v_dq_county_block_group_mismatch AS
SELECT c.year, c.st_case, c.county AS fars_county, bg.county_fips AS block_group_county, c.geoid10
FROM crash c
JOIN block_group bg ON bg.geoid10 = c.geoid10
WHERE bg.county_fips <> c.county;

-- 5. County-years with no population estimate (the rate would be too high).
CREATE VIEW v_dq_population_gap AS
SELECT co.county_fips, co.name AS county_name, y.year
FROM county co
CROSS JOIN generate_series(2020, 2024) AS y(year)
LEFT JOIN county_population cp ON cp.county_fips = co.county_fips AND cp.year = y.year
WHERE cp.county_fips IS NULL;

-- 6. Codes in the data that have no label for that year in code_lookup.
--    (BODY_TYP joins this list when its labels are loaded; see 07_seed_codes.sql.)
CREATE VIEW v_dq_unlabeled_code AS
WITH used(variable, year, code) AS (
    SELECT 'rur_urb',  year, rur_urb  FROM crash      UNION
    SELECT 'func_sys', year, func_sys FROM crash      UNION
    SELECT 'reljct2',  year, reljct2  FROM crash      UNION
    SELECT 'lgt_cond', year, lgt_cond FROM crash      UNION
    SELECT 'weather',  year, weather  FROM crash      UNION
    SELECT 'day_week', year, day_week FROM crash      UNION
    SELECT 'hit_run',  year, hit_run  FROM vehicle    UNION
    SELECT 'sex',      year, sex      FROM pedestrian UNION
    SELECT 'drinking', year, drinking FROM pedestrian UNION
    SELECT 'per_typ',  year, per_typ  FROM pedestrian UNION
    SELECT 'inj_sev',  year, inj_sev  FROM pedestrian UNION
    SELECT 'pbcwalk',  year, pbcwalk  FROM ped_crash_type UNION
    SELECT 'pbswalk',  year, pbswalk  FROM ped_crash_type UNION
    SELECT 'pedloc',   year, pedloc   FROM ped_crash_type UNION
    SELECT 'pedpos',   year, pedpos   FROM ped_crash_type
)
SELECT u.variable, u.year, u.code
FROM used u
LEFT JOIN code_lookup l
       ON l.variable = u.variable AND l.code = u.code AND u.year BETWEEN l.year_from AND l.year_to
WHERE l.code IS NULL;

-- 7. Columns that exist in the database but not in the data dictionary, and the reverse.
CREATE VIEW v_dq_undocumented_column AS
SELECT COALESCE(c.table_name, d.table_name)   AS table_name,
       COALESCE(c.column_name, d.column_name) AS column_name,
       CASE WHEN d.column_name IS NULL THEN 'in database, not in dictionary'
            ELSE 'in dictionary, not in database' END AS problem
FROM (SELECT table_name::text, column_name::text
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name NOT LIKE 'v\_dq\_%') c   -- the check views themselves are described in the SQL comments above
FULL JOIN data_dictionary d
       ON d.table_name = c.table_name AND d.column_name = c.column_name
WHERE c.column_name IS NULL OR d.column_name IS NULL;
