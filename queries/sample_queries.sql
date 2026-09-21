-- =====================================================================
-- queries/sample_queries.sql   six queries tied to the project question
--
--   psql -d ped_safety -f queries/sample_queries.sql
--
-- The central question has two halves:
--   (a) which COMBINATIONS of road class, posted speed, lighting, crossing
--       location, and time of day are most frequent among pedestrian deaths
--       on Florida's urban roads, and
--   (b) which COUNTIES concentrate the most deaths under each pattern.
-- Q1 and Q4 answer (a), Q2 and Q3 answer (b), Q5 feeds the dashboard heatmap,
-- and Q6 checks that the data can carry the answer (Objective 1).
--
-- With the 16 synthetic test rows the numbers mean nothing. What matters is that
-- each query runs, returns the right shape, and counts the edge cases correctly.
-- =====================================================================
\pset pager off

\echo
\echo == Q1. Which combinations of conditions are most frequent? (question, part a) ==
-- The SQL baseline for the association mining: every full combination of the five
-- attributes in the question, with its support (share of in-scope deaths).
SELECT road_class, speed_bin, light, crossing_location, time_of_day,
       count(*)                                           AS deaths,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS support_pct
FROM v_ped_transactions
GROUP BY road_class, speed_bin, light, crossing_location, time_of_day
ORDER BY deaths DESC, road_class, speed_bin, time_of_day
LIMIT 10;

\echo
\echo == Q2. Which counties concentrate the most deaths under one pattern? (question, part b) ==
-- Pattern: principal arterial + 45-50 mph + dark, not lighted + not at an intersection.
-- share_of_county_pct says how much of the county's in-scope toll the pattern explains.
WITH pattern AS (
    SELECT county_fips, county_name, count(*) AS pattern_deaths
    FROM v_ped_transactions
    WHERE road_class = 'principal arterial'
      AND speed_bin = '45-50 mph'
      AND light = 'dark, not lighted'
      AND crossing_location = 'not at intersection'
    GROUP BY county_fips, county_name
)
SELECT p.county_name,
       p.pattern_deaths,
       r.deaths_in_scope,
       round(100.0 * p.pattern_deaths / r.deaths_in_scope, 1)   AS share_of_county_pct,
       round(100000.0 * p.pattern_deaths / r.person_years, 3)   AS pattern_rate_per_100k_per_year
FROM pattern p
JOIN v_county_rate r ON r.county_fips = p.county_fips
ORDER BY p.pattern_deaths DESC, p.county_name;

\echo
\echo == Q3. Five-year county fatality rates per 100,000 residents (Objective 3) ==
-- All 67 counties are in the view; the ten with the highest rates are shown, then
-- one county with no deaths (rate 0, flagged unstable) to show it is not dropped.
(SELECT county_name, deaths_all, deaths_in_scope, person_years, rate_per_100k_per_year, unstable_rate
 FROM v_county_rate
 WHERE deaths_all > 0
 ORDER BY rate_per_100k_per_year DESC, county_name
 LIMIT 10)
UNION ALL
(SELECT county_name, deaths_all, deaths_in_scope, person_years, rate_per_100k_per_year, unstable_rate
 FROM v_county_rate
 WHERE county_name = 'Lafayette');

\echo
\echo == Q4. Does the pattern hold year after year? (Objective 2: stable in 4 of 5 years) ==
-- generate_series supplies all five years, so a year with no such death shows 0
-- instead of disappearing from the result.
SELECT y.year,
       count(t.st_case)                               AS pattern_deaths,
       (SELECT count(*) FROM v_ped_transactions a WHERE a.year = y.year) AS all_in_scope_deaths
FROM generate_series(2020, 2024) AS y(year)
LEFT JOIN v_ped_transactions t
       ON t.year = y.year
      AND t.road_class = 'principal arterial'
      AND t.speed_bin = '45-50 mph'
      AND t.light = 'dark, not lighted'
      AND t.crossing_location = 'not at intersection'
GROUP BY y.year
ORDER BY y.year;

\echo
\echo == Q5. Hour-by-lighting matrix for the dashboard heatmap ==
SELECT time_of_day,
       count(*) FILTER (WHERE light = 'daylight')               AS daylight,
       count(*) FILTER (WHERE light = 'dawn or dusk')           AS dawn_dusk,
       count(*) FILTER (WHERE light = 'dark, lighted')          AS dark_lighted,
       count(*) FILTER (WHERE light = 'dark, not lighted')      AS dark_not_lighted,
       count(*) FILTER (WHERE light IN ('dark, lighting unknown', 'unknown')) AS unknown,
       count(*)                                                 AS total
FROM v_ped_transactions
GROUP BY time_of_day
ORDER BY min(CASE time_of_day WHEN 'late night (0-5)' THEN 1 WHEN 'morning (6-9)' THEN 2
                              WHEN 'midday (10-15)' THEN 3 WHEN 'evening (16-19)' THEN 4
                              WHEN 'night (20-23)' THEN 5 ELSE 6 END);

\echo
\echo == Q6. Can the data carry the answer? Yearly counts and coverage (Objective 1) ==
-- deaths_all is the number to reconcile with NHTSA's published Florida totals (within 1%).
-- walkability_pct_of_geocoded must reach 90% (Objective 1).
SELECT c.year,
       count(*)                                                  AS deaths_all,
       count(*) FILTER (WHERE c.rur_urb = 2 AND c.func_sys NOT IN (1, 2)) AS deaths_in_scope,
       count(*) FILTER (WHERE c.latitude IS NOT NULL)            AS geocoded,
       round(100.0 * count(*) FILTER (WHERE c.geoid10 IS NOT NULL)
                   / NULLIF(count(*) FILTER (WHERE c.latitude IS NOT NULL), 0), 1) AS walkability_pct_of_geocoded,
       count(*) FILTER (WHERE p.str_veh IS NULL)                 AS no_striking_vehicle,
       count(*) FILTER (WHERE v.vspd_lim IN (98, 99))            AS speed_limit_unknown,
       count(*) FILTER (WHERE t.per_no IS NULL)                  AS no_typing_record
FROM pedestrian p
JOIN crash c ON c.year = p.year AND c.st_case = p.st_case
LEFT JOIN vehicle v ON v.year = p.year AND v.st_case = p.st_case AND v.veh_no = p.str_veh
LEFT JOIN ped_crash_type t ON t.year = p.year AND t.st_case = p.st_case AND t.veh_no = p.veh_no AND t.per_no = p.per_no
GROUP BY c.year
ORDER BY c.year;

\echo
\echo == Data-quality views: rows found (0 = clean; two of them list allowed cases) ==
SELECT 'v_dq_count_mismatch'              AS check_view, count(*) AS rows_found, 'must be 0' AS reading FROM v_dq_count_mismatch
UNION ALL SELECT 'v_dq_county_block_group_mismatch', count(*), 'must be 0 or explained' FROM v_dq_county_block_group_mismatch
UNION ALL SELECT 'v_dq_unlabeled_code',              count(*), 'must be 0'              FROM v_dq_unlabeled_code
UNION ALL SELECT 'v_dq_undocumented_column',         count(*), 'must be 0'              FROM v_dq_undocumented_column
UNION ALL SELECT 'v_dq_missing_typing',              count(*), 'allowed; Q7 has none'   FROM v_dq_missing_typing
UNION ALL SELECT 'v_dq_no_striking_vehicle',         count(*), 'allowed; Q10 has none'  FROM v_dq_no_striking_vehicle
UNION ALL SELECT 'v_dq_population_gap',              count(*), '300 = 60 counties x 5 years not in the fixture' FROM v_dq_population_gap;
