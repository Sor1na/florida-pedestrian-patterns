-- =====================================================================
-- tests/fixtures/valid_records.sql   16 synthetic pedestrian deaths in 15 crashes
--
-- EVERY ROW HERE IS MADE UP. The rows follow the real code lists, so they look
-- like FARS, but none is copied from a real case, and the population and
-- walkability numbers are placeholders in a realistic range. FARS describes
-- real deaths; the proposal keeps person-level rows out of the public repository.
--
-- R1-R3, E1, E2  the five records from the Week 4 conceptual model
--                (R1 now uses BODY_TYP 34: FARS replaced pickup codes 30/31 in 2020)
-- Q1-Q10         extra rows so the sample queries have something to rank
--
-- One transaction on purpose: the rule "a crash has at least one pedestrian and
-- one vehicle" is checked at COMMIT, so a crash and its children travel together.
-- =====================================================================
BEGIN;

INSERT INTO county_population (county_fips, year, population, vintage) VALUES
  (9,2020,606000,2025),  (9,2021,616000,2025),  (9,2022,627000,2025),  (9,2023,636000,2025),  (9,2024,645000,2025),
  (31,2020,996000,2025), (31,2021,1004000,2025),(31,2022,1016000,2025),(31,2023,1030000,2025),(31,2024,1040000,2025),
  (57,2020,1460000,2025),(57,2021,1478000,2025),(57,2022,1513000,2025),(57,2023,1543000,2025),(57,2024,1570000,2025),
  (67,2020,8226,2025),   (67,2021,8300,2025),   (67,2022,8350,2025),   (67,2023,8400,2025),   (67,2024,8450,2025),
  (86,2020,2700000,2025),(86,2021,2676000,2025),(86,2022,2690000,2025),(86,2023,2720000,2025),(86,2024,2760000,2025),
  (95,2020,1430000,2025),(95,2021,1436000,2025),(95,2022,1452000,2025),(95,2023,1480000,2025),(95,2024,1500000,2025),
  (105,2020,727000,2025),(105,2021,753000,2025),(105,2022,787000,2025),(105,2023,818000,2025),(105,2024,850000,2025);

-- county_fips is computed from the GEOID, so it is not listed. d4a NULL = no transit stop within 3/4 mile (EPA -99999).
INSERT INTO block_group (geoid10, natwalkind, d3b, d4a, totpop) VALUES
  ('120090651021',  7.17,  41.3,  NULL, 1842),
  ('120090712003',  6.00,  35.1,  NULL, 1575),
  ('120310144022',  5.50,  22.7,  NULL, 1310),
  ('120570119043',  8.33,  60.2, 655.0, 2210),
  ('120860042001', 14.83, 168.9, 412.5, 2105),
  ('120860091002', 16.17, 201.4, 150.0, 3120),
  ('120950145032', 10.67,  95.4, 780.0, 2960),
  ('121050120011',  4.83,  12.9,  NULL,  980);

INSERT INTO crash (year, st_case, county, month, day_week, hour, rur_urb, func_sys, reljct2, lgt_cond, weather,
                   latitude, longitud, geoid10, tway_id, fatals, peds) VALUES
  (2021,120417,  9, 11,6,21, 2,3,1,2, 1, 28.0791,-80.6752,'120090651021','US-192',      1,1),  -- R1 archetype
  (2023,120417, 86,  1,4,18, 2,4,2,3, 1, 25.8012,-80.2401,'120860042001','NW 27TH AVE', 1,1),  -- R2 same st_case as R1, other year
  (2022,121088, 31,  3,3, 5, 2,5,1,2, 2, 30.3312,-81.6560,'120310144022','MONCRIEF RD', 1,1),  -- R3
  (2024,120078, 95,  7,7,23, 2,3,1,3, 1, 28.4912,-81.4005,'120950145032','US-441',      2,2),  -- E1 one crash, two deaths
  (2022,121307, 57,  9,1, 2, 2,3,1,2, 1, NULL,   NULL,     NULL,          'SR-60',       1,1),  -- E2 no coordinates, no block group
  (2020,120233,  9,  2,7,20, 2,3,1,2, 1, 28.0803,-80.6698,'120090651021','US-192',      1,1),  -- Q1
  (2022,120655,  9, 12,5,22, 2,3,1,2,10, 28.3561,-80.7012,'120090712003','SR-520',      1,1),  -- Q2
  (2023,120981,  9, 10,2,19, 2,4,1,2, 1, 28.1144,-80.6403,'120090712003','WICKHAM RD',  1,1),  -- Q3
  (2020,121502, 57,  1,6,23, 2,3,1,2, 1, 27.9942,-82.4519,'120570119043','US-92',       1,1),  -- Q4
  (2024,120340, 57,  3,1, 4, 2,3,1,2, 1, 28.0330,-82.4572,'120570119043','US-41',       1,1),  -- Q5 unknown age, hit-and-run
  (2021,121777, 95,  8,5,21, 2,3,1,2, 1, 28.5523,-81.2954,'120950145032','SR-50',       1,2),  -- Q6 two vehicles; a second walker survived
  (2023,120052, 86,  4,6,20, 2,3,2,3, 1, 25.7743,-80.2089,'120860091002','SW 8TH ST',   1,1),  -- Q7 no typing record
  (2021,120890, 31,  6,4, 1, 2,1,1,2, 1, 30.2954,-81.6011,'120310144022','I-95',        1,1),  -- Q8 interstate: outside the analysis view
  (2022,121950,105,  5,7,22, 1,3,1,2, 1, 27.8950,-81.5860,'121050120011','US-27',       1,1),  -- Q9 rural: outside the analysis view
  (2024,121120, 86,  2,3,14, 2,4,2,1, 1, 25.7901,-80.2250,'120860042001','NW 7TH AVE',  1,1);  -- Q10 daylight; no striking-vehicle link

INSERT INTO vehicle (year, st_case, veh_no, body_typ, vspd_lim, hit_run) VALUES
  (2021,120417,1,34,45,0),
  (2023,120417,1, 4,35,0),
  (2022,121088,1,14,30,0),
  (2024,120078,1,15,45,0),
  (2022,121307,1,99,40,1),   -- E2: vehicle fled, body type unknown, speed limit known from the road
  (2020,120233,1, 4,45,0),
  (2022,120655,1,14,50,0),
  (2023,120981,1,34,45,1),
  (2020,121502,1,15,45,0),
  (2024,120340,1,99,45,1),
  (2021,121777,1, 4,45,0),
  (2021,121777,2,20,45,0),   -- Q6: the second vehicle is the one that struck the pedestrian
  (2023,120052,1, 4,40,0),
  (2021,120890,1,66,65,0),
  (2022,121950,1,34,55,0),
  (2024,121120,1,14,30,0);

INSERT INTO pedestrian (year, st_case, veh_no, per_no, str_veh, per_typ, inj_sev, age, sex, drinking) VALUES
  (2021,120417,0,1,   1,5,4, 47,1,0),
  (2023,120417,0,1,   1,5,4, 72,2,0),
  (2022,121088,0,1,   1,5,4, 34,1,9),   -- R3: unknown code kept as a value
  (2024,120078,0,1,   1,5,4, 29,1,1),
  (2024,120078,0,2,   1,5,4, 26,2,8),   -- E1: second death, same crash, same vehicle
  (2022,121307,0,1,   1,5,4, 58,1,1),
  (2020,120233,0,1,   1,5,4, 61,1,0),
  (2022,120655,0,1,   1,5,4, 39,1,1),
  (2023,120981,0,1,   1,5,4, 23,2,0),
  (2020,121502,0,1,   1,5,4, 52,1,9),
  (2024,120340,0,1,   1,5,4,999,1,9),   -- Q5: age unknown
  (2021,121777,0,1,   2,5,4, 44,1,0),   -- Q6: struck by vehicle 2
  (2023,120052,0,1,   1,5,4, 67,2,0),
  (2021,120890,0,1,   1,5,4, 31,1,1),
  (2022,121950,0,1,   1,5,4, 55,1,0),
  (2024,121120,0,1,NULL,5,4, 81,2,0);   -- Q10: no striking-vehicle link (allowed)

INSERT INTO ped_crash_type (year, st_case, veh_no, per_no, pbcwalk, pbswalk, pedloc, pedpos, pedctype) VALUES
  (2021,120417,0,1, 0,0,3,3,760),
  (2023,120417,0,1, 1,1,1,2,781),
  (2022,121088,0,1, 0,0,3,4,410),
  (2024,120078,0,1, 0,1,3,3,770),
  (2024,120078,0,2, 0,1,3,3,770),
  (2022,121307,0,1, 0,0,3,3,620),
  (2020,120233,0,1, 0,0,3,3,760),
  (2022,120655,0,1, 0,1,3,3,741),
  (2023,120981,0,1, 0,1,3,3,760),
  (2020,121502,0,1, 0,0,3,3,760),
  (2024,120340,0,1, 0,0,3,3,760),
  (2021,121777,0,1, 0,1,3,3,770),
  -- Q7 (2023,120052) has no typing record on purpose
  (2021,120890,0,1, 0,0,3,3,910),
  (2022,121950,0,1, 0,0,3,4,430),
  (2024,121120,0,1, 1,1,1,2,792);

-- One made-up pipeline run, so the bookkeeping tables are exercised too.
-- The checksum is a placeholder (64 zeros), not the checksum of any real file.
INSERT INTO etl_run (started_at, finished_at, git_commit, status)
VALUES ('2026-09-20 18:00:00-04', '2026-09-20 18:04:12-04', 'cd0e009', 'succeeded');

INSERT INTO source_file (run_id, source, data_year, release, file_name, url, sha256, retrieved_on)
SELECT run_id, 'FARS', 2024, 'Annual Report File', 'FARS2024NationalCSV.zip',
       'https://static.nhtsa.gov/nhtsa/downloads/FARS/2024/National/FARS2024NationalCSV.zip',
       repeat('0', 64), DATE '2026-09-08'
FROM etl_run;

INSERT INTO etl_log (run_id, step, rows_in, rows_out, status, message)
SELECT run_id, 'filter person file to Florida pedestrian fatalities', 92000, 16, 'ok', 'synthetic example' FROM etl_run;

INSERT INTO validation_result (run_id, check_name, passed, detail)
SELECT run_id, 'every str_veh resolves to a vehicle in the same crash', true, '15 of 15 non-null links resolve' FROM etl_run;

COMMIT;
