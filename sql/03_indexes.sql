-- =====================================================================
-- 03_indexes.sql
-- Every PRIMARY KEY, UNIQUE, and EXCLUDE constraint already has its own index.
-- These are the extra ones. Each covers a foreign key that is not the leading
-- part of a primary key, which helps in two places: the join in that direction,
-- and the check PostgreSQL runs on the child table when a parent row is deleted.
--
-- Honest note: with about 3,700 pedestrian rows the planner will usually pick a
-- sequential scan anyway. The indexes cost almost nothing at this size and they
-- start to matter if the scope grows from Florida to all states.
-- =====================================================================

-- crash -> county: county rates, "which counties concentrate a pattern"
CREATE INDEX crash_county_ix ON crash (county);

-- crash -> block_group: walkability join; only geocoded crashes have a value
CREATE INDEX crash_geoid10_ix ON crash (geoid10) WHERE geoid10 IS NOT NULL;

-- pedestrian -> vehicle: the "is struck by" join; rows without a link are skipped
CREATE INDEX pedestrian_striking_vehicle_ix ON pedestrian (year, st_case, str_veh) WHERE str_veh IS NOT NULL;

-- block_group -> county: county-level walkability fallback
CREATE INDEX block_group_county_ix ON block_group (county_fips);

-- ped_crash_type -> pbcat_type, pbcat_type -> pbcat_group: label joins
CREATE INDEX ped_crash_type_pedctype_ix ON ped_crash_type (pedctype);
CREATE INDEX pbcat_type_group_ix ON pbcat_type (pedcgp);

-- pipeline tables: look up everything that belongs to one run
CREATE INDEX etl_log_run_ix ON etl_log (run_id, logged_at);
