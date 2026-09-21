#!/usr/bin/env bash
# Rebuilds the database from nothing, loads the synthetic fixture, runs the constraint
# tests and the sample queries, and writes the evidence logs under docs/evidence/.
#
#   createdb ped_safety          (once)
#   bash tests/run_all.sh        (from the repository root)
#
# Connection settings come from the usual PostgreSQL environment variables
# (PGHOST, PGPORT, PGUSER) or from your own ~/.pgpass. Nothing is stored here.
set -euo pipefail
DB="${PGDATABASE:-ped_safety}"
OUT=docs/evidence
mkdir -p "$OUT"

psql -X -q -d "$DB" -v ON_ERROR_STOP=1 -f sql/00_build_all.sql              > "$OUT/01_build.log" 2>&1
psql -X -q -d "$DB" -v ON_ERROR_STOP=1 -f tests/fixtures/valid_records.sql  > "$OUT/02_load_valid_records.log" 2>&1
psql -X -q -d "$DB" -c "SELECT 'county' AS table_name, count(*) AS row_count FROM county UNION ALL SELECT 'county_population', count(*) FROM county_population UNION ALL SELECT 'block_group', count(*) FROM block_group UNION ALL SELECT 'code_lookup', count(*) FROM code_lookup UNION ALL SELECT 'pbcat_group', count(*) FROM pbcat_group UNION ALL SELECT 'pbcat_type', count(*) FROM pbcat_type UNION ALL SELECT 'crash', count(*) FROM crash UNION ALL SELECT 'vehicle', count(*) FROM vehicle UNION ALL SELECT 'pedestrian', count(*) FROM pedestrian UNION ALL SELECT 'ped_crash_type', count(*) FROM ped_crash_type UNION ALL SELECT 'data_dictionary', count(*) FROM data_dictionary UNION ALL SELECT 'v_ped_transactions (view)', count(*) FROM v_ped_transactions" >> "$OUT/02_load_valid_records.log" 2>&1
psql -X -q -d "$DB" -f tests/test_constraints.sql                           > "$OUT/03_constraint_tests.log" 2>&1
psql -X -q -d "$DB" -f queries/sample_queries.sql                           > "$OUT/04_sample_queries.log" 2>&1
python3 tests/check_code_domains.py                                         > "$OUT/05_code_domain_check.log" 2>&1

echo "PostgreSQL: $(psql -X -At -d "$DB" -c 'SHOW server_version')"
tail -n 9 "$OUT/03_constraint_tests.log" | head -n 4
echo "Logs written to $OUT/"
