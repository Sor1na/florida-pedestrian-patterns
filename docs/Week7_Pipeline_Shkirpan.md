# Week 7: Pipeline Runs, Reruns, Failures, and Recovery

**Built for Cars, Deadly for Walkers: mining the roadway conditions behind Florida's pedestrian deaths, 2020–2024**

Yelysei Shkirpan · Capstone Project, B.S. Data Science · Eastern Florida State College · October 5, 2026

Repository: https://github.com/Sor1na/florida-pedestrian-patterns

**What this week adds.** Weeks 4–6 designed the database and fixed the cleaning rules. This week the rules run: `pipeline/etl.py` takes the pinned raw files to the tables of the Week 5 schema through eleven stages and six validation gates, logs every step with its run ID, time, and row counts, and can be run again at any time without changing a correct database. `pipeline/run_scenarios.py` exercises it end to end and keeps the evidence: a first run, a rerun of the same inputs, two deliberate failures, and a process killed in the middle of the load followed by a restart.

**Reproduce everything in this document** (PostgreSQL 16, Python 3.11 with `pip install -r requirements.txt`, from the repository root):

```
createdb ped_safety
python pipeline/run_scenarios.py --synthetic     # rebuilds the database, runs all scenarios, writes docs/evidence/week7_synthetic/
python pipeline/run_scenarios.py                 # the same scenarios on the real files in data/raw/ -> docs/evidence/week7/
```

**Which inputs the evidence comes from.** FARS rows describe real deaths, and the proposal keeps person-level rows out of the public repository, so the logs committed here come from **synthetic input files** made by `tools/make_synthetic_raw.py`. They have the exact layout of the real downloads: the same zip names, member names (upper and lower case, with and without a folder), column names, the cp1252 encoding of three 2020 members, the Census file in latin-1 with the state summary row, coded unknowns, filler coordinates, multi-victim crashes, and case numbers reused across years. Every row in them is made up, and the generator is deterministic, so the SHA-256 values in the logs can be reproduced by anyone. The real files are pinned in `pipeline/sources.csv` with the checksums measured in Week 6 (`docs/profile/00_manifest_sha256.csv`), and the reconciliation totals in `pipeline/expected_counts.csv` are the Week 6 profile numbers (3,736 deaths in 3,690 crashes). The second command above runs the same six scenarios on the real files and writes `docs/evidence/week7/`, with case numbers masked.

---

## 1. Pipeline stages and dependencies

![Pipeline stages, gates, and evidence](pipeline.png)

Diagram source: [`docs/pipeline.mmd`](pipeline.mmd) (Mermaid; also [`pipeline.svg`](pipeline.svg)). The order is defined once, in `STAGES` in `pipeline/etl.py`; the runner refuses to start a stage whose dependencies have not finished, and `python pipeline/etl.py stages` prints the list below from the code.

| # | Stage | Runs after | Gate | What it does | A failure means |
|---|---|---|---|---|---|
| 1 | `preflight` | (start) | — | Connects, takes an advisory lock so only one run can work at a time, closes any run left `running` by a dead process, inserts the `etl_run` row (run ID, start time, git commit), and fingerprints the five data tables. | Exit 3 if another run holds the lock; exit 2 if the database is not built. |
| 2 | `verify_sources` | 1 | **G1 integrity** | Every file in `sources.csv` is present, and its size and SHA-256 equal the pinned values. Writes one `source_file` row per file (source, year, release Final / Annual Report File, URL, SHA-256, retrieval date). | A raw file is missing or changed. Nothing is read. |
| 3 | `extract` | 2 | **G2 structure** | Reads `accident`, `vehicle`, `person`, `pbtype` from each zip by name (case and folder do not matter), decodes UTF-8 with a cp1252 fallback, checks that every required column exists, keeps STATE = 12. Reads the Census file (latin-1) and keeps the 67 county rows. | A member or a required column is missing (schema drift). |
| 4 | `reconcile_inventory` | 3 | **G3** | Florida rows per member and year equal `expected_counts.csv` (for the real files: the Week 6 profile, `docs/profile/01_inventory.csv`). | The file is not the one that was profiled. |
| 5 | `transform` | 4 | — | Builds the unit of observation (PER_TYP 5 and INJ_SEV 4), its crashes, their in-transport vehicles and the typing records; filler coordinates (77.7777 / 88.8888 / 99.9999) become NULL; STR_VEH 0 or an unresolved STR_VEH becomes NULL with a warning (rule 2: the death is kept); Census to one row per county and year. Every step logs rows in and out. | (no gate) |
| 6 | `join_block_groups` | 5 | — | EPA spatial join for `crash.geoid10`. **Skipped with a logged warning** until the EPA file is pinned in `sources.csv` (cleaning plan, issue 5). | (no gate) |
| 7 | `validate_records` | 5 | **G4 record rules** | pandera schemas, as the proposal planned. Raw layer: unique keys within the year, no orphan rows. Record layer: whole-number types, the schema's CHECK ranges, codes that have a label **valid for that year** in `code_lookup`, county in the 67, PEDCTYPE in `pbcat_type`. Every failing record goes to `rejected_record` with file, member, line, key, rule, column, value, and the raw source values. | One or more records rejected. Nothing is published. |
| 8 | `reconcile_unit` | 7 | **G5** | Pedestrian fatalities and crashes per year equal the published totals (real files: 695 / 819 / 780 / 774 / 668 deaths). | Rows were lost or gained between file and unit. |
| 9 | `load` | 6, 8 | — | **One transaction**: deletes 2020–2024 from `crash` (cascading to vehicle, pedestrian, ped_crash_type) and from `county_population`, inserts with COPY, then runs the deferred "one or more" triggers. Logs per year and table: rows deleted from the previous load, rows inserted. | A constraint or trigger refuses a row: rollback. |
| 10 | `verify_load` | 9 | **G6 post-load** | Inside the same open transaction: rows per year equal the rows prepared, no duplicate keys, pedestrian rows equal the published totals, the `v_dq_*` views return nothing, every crash has a pedestrian and a vehicle, county rates cover every death, five FARS `source_file` rows for the run. **COMMIT only if every blocking check passes**, otherwise ROLLBACK. | Rollback; the previous load stays. |
| 11 | `finalize` | 10 | — | Row counts and an md5 content fingerprint of each data table, one lineage line per year, `etl_run.status = 'succeeded'`. | — |

Two connections make the failure behaviour visible. The **load connection** holds the one transaction of stages 9–10. The **bookkeeping connection** runs in autocommit and writes `etl_run`, `source_file`, `etl_log`, `validation_result`, and `rejected_record` as the run goes, so the evidence of a failed run survives the rollback of its load. Each check is one `validation_result` row; checks marked "warning only" are reported but do not block (pedestrians without a typing record, without a striking vehicle, and the block-group share while the EPA join is pending).

### Data lineage

| Raw source (pinned) | Member / rows used | Stage that filters it | Target | Real files (Week 6 profile) |
|---|---|---|---|---|
| `FARS{year}NationalCSV.zip` | `accident.csv`, STATE = 12 | extract → transform (crashes with a pedestrian death) | `crash` | 15,959 Florida rows → 3,690 crashes |
| same | `vehicle.csv`, STATE = 12 | extract → transform (vehicles of those crashes) | `vehicle` | 25,203 Florida rows |
| same | `person.csv`, STATE = 12 | extract → transform (PER_TYP 5, INJ_SEV 4) | `pedestrian` | 41,133 Florida rows → 3,736 deaths |
| same | `pbtype.csv`, STATE = 12 | extract → transform (records of those deaths) | `ped_crash_type` | 5,193 Florida rows → 3,736 |
| `co-est2025-alldata.csv` | SUMLEV 050, STATE 12 | extract → transform (county × year) | `county_population` | 67 counties × 5 years = 335 |
| (EPA SLD, not yet pinned) | — | join_block_groups (skipped) | `block_group`, `crash.geoid10` | — |

The chain is recorded for every run: `source_file` ties the run to the exact files (SHA-256 and release), `etl_log` holds the rows in and out of every filter, G3 and G5 compare the counts with the Week 6 profile, and `finalize` writes one line per year from file to loaded rows, for example (synthetic run 1):

```
lineage 2024: FARS2024NationalCSV.zip sha256 92ea36b04dee (Annual Report File) -> person 1,124 national -> 636 Florida -> 110 pedestrian fatalities loaded
```

---

## 2. One successful end-to-end run

Evidence: [`docs/evidence/week7_synthetic/01_first_run.log`](evidence/week7_synthetic/01_first_run.log) and the full run log [`runs/run_0001.log`](evidence/week7_synthetic/runs/run_0001.log) (204 lines).

Run 1 started on an empty database (fingerprint of the empty tables `6891cd577154`), passed all six gates with **92 checks passed, 0 blocking failures, 1 warning** (block-group share 0%, because the EPA join is not run yet), and committed in about 1.5 seconds on the synthetic files.

| Stage | Rows in → out (2020–2024 together) |
|---|---|
| verify_sources | 6 files → 6 verified, 6 `source_file` rows |
| extract | accident 2,297 → 1,304 Florida; vehicle 3,248 → 1,801; person 5,860 → 3,399; pbtype 1,334 → 877; census 79 → 67 |
| transform | person 3,399 → 596 pedestrian fatalities; accident 1,304 → 547 crashes (6 filler coordinate pairs set to NULL); vehicle 1,801 → 629; pbtype 877 → 596; census 67 → 335 county-years |
| validate_records | 10,084 rows checked → 0 rejected |
| reconcile_unit | deaths per year 130 / 120 / 104 / 132 / 110 = expected; crashes 120 / 112 / 94 / 122 / 99 = expected |
| load | deleted 0, inserted crash 547, vehicle 629, pedestrian 596, ped_crash_type 596, county_population 335 |
| verify_load | 27 post-load checks: 26 passed, 1 warning; COMMIT |

Final state (from `python pipeline/etl.py snapshot`):

```
table             | rows | 2020 | 2021 | 2022 | 2023 | 2024 | content md5
crash             | 547  | 120  | 112  | 94   | 122  | 99   | 49cf6a3c7e59
vehicle           | 629  | 137  | 128  | 104  | 148  | 112  | dab639db2ca6
pedestrian        | 596  | 130  | 120  | 104  | 132  | 110  | ebeb2b2edf7d
ped_crash_type    | 596  | 130  | 120  | 104  | 132  | 110  | 551cb57394a5
county_population | 335  | 67   | 67   | 67   | 67   | 67   | 84cbd56a35e4
fingerprint of all data tables: 2a6d36a623b35c2540a9df5cb5c53161
```

The same run also reports the provisional-year detector of cleaning-plan issue 2 (RUR_URB not reported: 10.0% of 2024 deaths against at most 0.8% in 2020–2023 in the synthetic files) and keeps the 2024 file labelled `Annual Report File` in `source_file`.

---

## 3. Rerun with the same inputs: duplicate prevention

Evidence: [`02_rerun_same_inputs.log`](evidence/week7_synthetic/02_rerun_same_inputs.log).

Run 2 used the same command and the same files. It passed every gate and replaced each year instead of adding to it:

```
run=2 stage=load INFO rows_in=130 rows_out=130 | 2020 pedestrian: deleted 130 row(s) of the previous load, inserted 130
...
run=2 stage=finalize INFO | fingerprint of the data tables after the run: 2a6d36a623b35c2540a9df5cb5c53161 (identical to before the run: the rerun changed nothing)
```

The snapshot before and after the rerun is identical: same row counts per table and year, same md5 of every table's content, same combined fingerprint `2a6d36a6…`. Four mechanisms make this hold, and each one leaves evidence:

1. **Composite keys.** `crash (year, st_case)`, `vehicle (year, st_case, veh_no)`, `pedestrian` and `ped_crash_type (year, st_case, veh_no, per_no)`, `county_population (county_fips, year)`. A second copy of a row cannot be stored, and a 2021 case cannot collide with the 2023 case that reuses its number.
2. **Replace by year in one transaction.** The load deletes the five years and inserts them again before anyone can see the result; the log shows "deleted N, inserted N" for every table and year.
3. **G6 checks the result before COMMIT**: rows per year equal the rows prepared, `count(*) = count(DISTINCT key)` for every table, and pedestrian rows per year equal the published totals.
4. **Content fingerprint.** `preflight` and `finalize` compute an md5 over every row of the five data tables; equal fingerprints mean the rerun changed nothing.

Bookkeeping grows by design: each run adds its own `etl_run`, `source_file`, `etl_log`, and `validation_result` rows, which is what makes runs comparable.

---

## 4. Two deliberate failures and the system's response

### Failure A: a raw file edited after it was pinned (gate G1)

Evidence: [`03_failure_tampered_file.log`](evidence/week7_synthetic/03_failure_tampered_file.log). The scenario copies the inputs, changes one AGE value (35 → 47) in `person.csv` inside the 2022 zip and re-zips it, which is what opening the CSV in a spreadsheet and saving it would do. `sources.csv` is not updated.

```
run=3 stage=verify_sources ERROR | FAIL  G1 sha256 FARS2022NationalCSV.zip: expected 9dab6eb7cd4d0f94... (33,427 bytes), found 73025c648f7ae676... (33,430 bytes)
run=3 stage=verify_sources ERROR | gate failed at stage verify_sources: G1 integrity: 1 blocking check(s) failed: G1 sha256 FARS2022NationalCSV.zip
run=3 stage=verify_sources INFO | data tables unchanged by this run: True (fingerprint 2a6d36a623b3); they still hold the load of run 2
run=3 stage=end ERROR | RUN 3 FAILED at stage verify_sources; see docs/Week7_Pipeline_Shkirpan.md, section 6 (recovery)
```

Response: exit code 1, `etl_run` 3 = `failed`, no member was read, no `source_file` row was written for the run, and the data tables are unchanged (same fingerprint; the snapshot after the scenario equals the one after run 2).

### Failure B: a new file version with four bad records (gate G4)

Evidence: [`04_failure_bad_records.log`](evidence/week7_synthetic/04_failure_bad_records.log). The scenario writes a new version of the 2023 zip with four defects, one for each kind of problem the cleaning plan says must stop a load, and accepts the new file's hash and row inventory into a copy of `sources.csv` and `expected_counts.csv`, the way a re-download would be accepted. Gates G1–G3 therefore pass, and the record-level gate has to find the defects:

| Injected defect | Cleaning-plan reference | Caught by | Rejected record |
|---|---|---|---|
| (a) exact duplicate of a pedestrian-fatality person row | issue 3 (a duplicate is a pipeline error) | G4 raw keys `person` | `person 120002/0/1`, line 124: duplicate key within the year |
| (b) LGT_COND = 42 on a crash | issue 4 (an unlabelled code stops the load) | G4 record rules `crash` | `crash 2023/120003`, `lgt_cond = 42`: code with a 2023 label in code_lookup |
| (c) COUNTY = 999 on a crash | rule 3 (county mandatory and one of the 67) | G4 record rules `crash` | `crash 2023/120004`, `county = 999`: one of the 67 Florida counties |
| (d) a pedestrian death and its typing record whose crash is not in accident.csv | rule 1 (no orphans) | G4 raw keys `person`, `pbtype` | `person 129999/0/1` and `pbtype 129999/0/1`: ST_CASE exists in accident.csv (no orphan) |

```
run=4 stage=validate_records ERROR rows_in=10090 rows_out=10085 | record-level rules applied to 10,090 rows; 5 rejected into rejected_record
run=4 stage=validate_records ERROR | gate failed at stage validate_records: G4 record rules (5 record(s) in rejected_record, run 4): 3 blocking check(s) failed: ...
run=4 stage=validate_records INFO | data tables unchanged by this run: True (fingerprint 2a6d36a623b3); they still hold the load of run 2
```

Response: exit code 1, run 4 = `failed`, five rows in `rejected_record` (four defects; the orphan death brings its typing record with it), `python pipeline/etl.py rejected --run 4` lists them with file, member, CSV line, key, rule, column and value, and the published tables are unchanged. The orphan death also produced the rule-2 warning in `transform` (its striking vehicle cannot be resolved), which is the behaviour the plan asks for: a warning, not a silent drop.

### Additional: a process killed inside the load, then restarted

Evidence: [`05_interrupted_run.log`](evidence/week7_synthetic/05_interrupted_run.log), [`06_restart_after_interrupt.log`](evidence/week7_synthetic/06_restart_after_interrupt.log). Run 5 was started with `--simulate-crash-after load`, which ends the process with `os._exit(70)` after all rows had been inserted but before COMMIT, as a power cut or a killed terminal would. PostgreSQL rolled the open transaction back when the connection dropped; the snapshot is unchanged and `etl_run` 5 is left `running`. Run 6, the same command again, found it:

```
run=6 stage=preflight WARN | recovered abandoned run 5 (...): status set to failed; its load transaction was never committed, so no rows of it exist
run=6 stage=finalize INFO | fingerprint of the data tables after the run: 2a6d36a623b35c2540a9df5cb5c53161 (identical to before the run: the rerun changed nothing)
run=6 stage=end INFO | RUN 6 SUCCEEDED
```

---

## 5. Logs: run ID, timestamps, row counts, errors

Every run leaves the same evidence in four places:

| Where | What one record holds | How to read it |
|---|---|---|
| `logs/run_NNNN.log` (ignored by Git; the cited runs are copied to `docs/evidence/week7_synthetic/runs/`) | ISO timestamp with UTC offset, `run=`, `stage=`, level, `rows_in=` / `rows_out=` where rows move, message | any text editor; `grep "ERROR\|WARN" logs/run_0004.log` |
| `etl_run` | run ID, start, finish, git commit, status running / succeeded / failed | `python pipeline/etl.py status` |
| `etl_log` | run ID, step, rows in, rows out, ok / warning / error, message, logged_at | `python pipeline/etl.py status --run N` |
| `validation_result` | run ID, check name with its gate (G1–G6), passed, detail, checked_at | same command (failed checks listed) |
| `rejected_record` | run ID, year, file, member, CSV line, target table, key, rule, column, failing value, raw source values (JSON), rejected_at | `python pipeline/etl.py rejected --run N` |

Excerpts (synthetic runs; full files under `docs/evidence/week7_synthetic/`):

```
# a row-count line (stage transform, run 1)
2026-10-05T01:20:33.271+00:00 run=1 stage=transform INFO rows_in=718 rows_out=130 | 2020 person -> pedestrian: PER_TYP = 5 and INJ_SEV = 4

# a gate passing, with expected and actual values (run 1)
... run=1 stage=reconcile_unit INFO | PASS  G5 2024 ped_fatalities: published/profiled 110, derived 110

# an error with the record that caused it (run 4)
... run=4 stage=validate_records ERROR | REJECT crash 2023/120003 (FARS2023NationalCSV.zip:accident.csv line 54): code with a 2023 label in code_lookup [lgt_cond=42]

# the run outcome (run 3)
... run=3 stage=end ERROR | RUN 3 FAILED at stage verify_sources; see docs/Week7_Pipeline_Shkirpan.md, section 6 (recovery)
```

The run history across all six runs, read back from the database, is in [`07_run_history.log`](evidence/week7_synthetic/07_run_history.log): runs 1, 2 and 6 succeeded; 3 (G1), 4 (G4) and 5 (killed, closed by run 6) failed; the error lines of every run and the load and finalize lines with their row counts follow.

The synthetic logs were recorded in a Linux container on UTC; the timestamps from PostgreSQL (`started_at`) are shown in the database's time zone (America/New_York). Both carry their offset, so they compare correctly.

---

## 6. Restart, recovery, and rejected-record instructions

### 6.1 Normal run and rerun

```
python pipeline/etl.py run          # defaults: data/raw/, pipeline/sources.csv, pipeline/expected_counts.csv, logs/
python pipeline/etl.py status       # did it succeed? which stage failed? which checks?
```

A rerun is always safe: it either replaces 2020–2024 completely and passes every gate, or it changes nothing. There is no partial state to clean up and no "resume from stage N" step; restarting means running the same command again. The whole run takes seconds on the synthetic files and well under a minute on the real ones (the Week 6 profile read the same zips in about 30 seconds).

| Exit code | Meaning | What to do |
|---|---|---|
| 0 | succeeded; tables replaced and verified | nothing |
| 1 | a gate failed or an error occurred; tables unchanged | `etl.py status`, then 6.3 |
| 2 | could not start (database unreachable or not built) | check the PG* variables; build with `sql/00_build_all.sql` on a new database |
| 3 | another run holds the lock | wait for it; never run two at once |
| 70 | only with `--simulate-crash-after` (test) | run again |

### 6.2 Diagnose a run

1. `python pipeline/etl.py status --run N`: the `etl_run` row, every `etl_log` step with rows in and out, the failed checks with their details, and the number of rejected records.
2. `logs/run_NNNN.log`: the same steps with millisecond timestamps, plus the traceback of an unexpected error.
3. `python pipeline/etl.py rejected --run N`: the quarantined records.
4. `python pipeline/etl.py snapshot`: row counts and fingerprints now; compare with the `finalize` lines of the last succeeded run.

### 6.3 Recovery by failure

| Failed at | Typical cause | Recovery |
|---|---|---|
| G1 `verify_sources` | a raw file was changed, replaced, truncated, or is missing | Never edit a raw file to make it pass. Restore the original from the backup or download it again from the URL in `sources.csv`; check `sha256sum` equals the pinned value; rerun. If NHTSA really published a new version, follow 6.5. |
| G2 `extract` | NHTSA renamed or dropped a column, or a member is missing | Confirm in the FARS manual; map the new name in `REQUIRED` in `etl.py` in a reviewed commit; rerun. |
| G3 `reconcile_inventory` | the file is not the one profiled (different release) | Rerun `pipeline/profile_raw.py` on it, compare with `docs/profile/`, and only then update `expected_counts.csv` (6.5). |
| G4 `validate_records` | bad or unexpected records | 6.4. |
| G5 `reconcile_unit` | deaths lost or gained between file and unit | Compare the transform lines of `etl_log` with the profile; a difference is a code defect, fix it before rerunning. |
| G6 `verify_load` or a constraint error in `load` | the load would break a rule the earlier gates did not see | The transaction was rolled back. Read the failed check (`status --run N`); fix the rule or the data source; rerun. |
| process killed, machine restarted, connection lost | — | Run the same command. The next run closes the abandoned `etl_run` row as `failed`; the uncommitted load never existed. |
| exit 3 (lock held) | a run is in progress, or a crashed session still holds its connection | Wait. If no run is active, the lock disappears when the old connection ends (`SELECT pid, state FROM pg_stat_activity` shows it). |

Rolling back to an earlier good load is a rerun with the earlier inputs: check out the `sources.csv` / `expected_counts.csv` of that commit, keep the matching raw files, and run. The load replaces 2020–2024, so no manual delete is needed.

### 6.4 Rejected records

1. **Read them.** `python pipeline/etl.py rejected --run N` lists file, member, CSV line, key, rule, column, and value; `SELECT raw_record FROM rejected_record WHERE run_id = N` shows the source values as read. Nothing in a raw file is ever edited, and nothing was published.
2. **Decide what the record is.** Every rejection is one of three cases:
   - *The record is right and the rule is incomplete*: for example, a new FARS code that is documented in the current Analytical User's Manual. Add the label to `sql/07_seed_codes.sql` (with `year_from`), and the code to the column's CHECK in `sql/01_schema.sql` if needed, commit, rebuild the database, rerun.
   - *The file is wrong*: duplicates, orphans, a truncated or corrupted download. Download it again, verify the checksum, rerun. Report a defect in an official file to NHTSA rather than patching it.
   - *The record is real but outside the rules on purpose*: for example, COUNTY 999 (unknown). The plan keeps every death in a county rate, so this needs a written decision (an `unknown county` reference row, or exclusion with a count in the report), recorded in the cleaning plan before the rule changes. It is never dropped silently.
3. **Rerun.** When the rerun passes G4, the death is loaded with all others. The old `rejected_record` rows stay as the history of the failed run; they are removed only together with their `etl_run` row (`ON DELETE CASCADE`).
4. **Privacy.** `rejected_record.raw_record` and `record_key` hold case-level values, marked Restricted in the data dictionary; they stay in the local database. Evidence published from real files uses `--redact-keys`, which masks case numbers in the log and in the rejected listing.

The gate tolerates **zero** rejected records. The raw files profiled in Week 6 contain no duplicates, orphans, or unlabelled codes, so a rejected record is a signal that the input or the rules changed, and loading the rest would quietly change the count of deaths, which is the unit of the project.

### 6.5 Accepting a new source version (the 2024 Final file)

1. Download it to `data/raw/` under a new name (keep the Annual Report File until the end of the project); make it read-only.
2. `python pipeline/profile_raw.py` against it and review the differences with the profile (cleaning plan, issue 2).
3. Update the 2024 row in `pipeline/sources.csv` (file name, bytes, SHA-256, `release = Final`, retrieval date) and the 2024 rows of `pipeline/expected_counts.csv`; commit.
4. `python pipeline/etl.py run`. The 2024 rows are replaced, not added; `source_file` records the new release; G6 confirms 2020–2023 are unchanged.

---

## 7. Completion criteria

| Criterion | Where it is shown |
|---|---|
| The pipeline can be rerun safely | Section 3 (identical fingerprints after a rerun), scenario 6 (restart after a killed run), section 6.1 |
| Validation gates and failure behaviour are visible | Section 1 (six gates), section 4 (G1 and G4 failures with the database unchanged), `validation_result` and `rejected_record` |
| Logs contain enough evidence to diagnose a run | Section 5: run ID, timestamp with offset, stage, rows in/out, the failing check with expected and actual values, the rejected record with file and line |
| Recovery steps are explicit | Section 6: exit codes, diagnosis steps, a recovery table per gate, rejected-record procedure, new-version procedure |
| Results connect to the documented data lineage | Section 1 lineage table; `source_file` (SHA-256, release) per run; G3 and G5 against the Week 6 profile counts; the per-year lineage lines in `finalize` |

---

## 8. Methods basis

The validation stages implement the data-quality concepts of the course text (Tan, Steinbach, Karpatne, & Kumar, 2019, chapter 2, "Data"). Measurement and data-collection problems are checked where they can enter: an altered or incomplete file (G1, G3), missing attributes (G2), and values outside an attribute's domain (G4). Missing values are handled as decided in Week 6: FARS unknown codes stay as values, and only the documented fillers for coordinates become NULL. Inconsistent values are found by comparing facts recorded twice (FATALS against the pedestrian rows, the county code against the block group, the published totals against the derived unit in G5). Duplicate data is tested on keys, after establishing in Week 6 that look-alike rows (multi-victim crashes, reused case numbers) are distinct objects, so the pipeline never deduplicates. The provisional 2024 file is the book's timeliness problem, handled through the release label and the replace-by-year load. The aggregation and discretization that prepare the transactions for association analysis (chapters 5–6) stay in the view `v_ped_transactions`, so the loaded data keep the codes exactly as published.

## 9. Limitations and next steps

- **The committed logs are from synthetic files.** The pipeline, the checksums, and the expected counts for the real files are in place; running `python pipeline/run_scenarios.py` with the real zips in `data/raw/` produces the same evidence in `docs/evidence/week7/` with the real counts (3,736 deaths). A real-data run can still reveal a code that the seeds do not label; G4 then stops the load, and 6.4 applies.
- **The EPA block-group join is not implemented yet.** The stage exists in the order and logs itself as skipped; `crash.geoid10` is NULL and the walkability item reads `unknown` until the EPA file is pinned. The block-group share check is a warning, not a gate, until then.
- **Single machine, single user.** The advisory lock prevents concurrent runs on one database; there is no scheduler, because the sources change at most once a year.

## Sources and AI assistance

- Tan, P.-N., Steinbach, M., Karpatne, A., & Kumar, V. (2019). *Introduction to data mining* (2nd ed.). Pearson. Chapter 2 (data quality and preprocessing); chapters 5–6 (association analysis).
- National Highway Traffic Safety Administration. (2026). *Fatality Analysis Reporting System (FARS): National CSV files 2020–2024*. https://static.nhtsa.gov/nhtsa/downloads/FARS/
- National Highway Traffic Safety Administration. (2026). *FARS analytical user's manual, 1975–2024*. https://static.nhtsa.gov/nhtsa/downloads/FARS/Links%20for%20FARS%20Manuals.pdf
- U.S. Census Bureau. (2026). *County population totals: 2020–2025, Vintage 2025* (CO-EST2025-ALLDATA). https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html
- pandera (Union.ai), data validation for pandas; psycopg 3; PostgreSQL 16 documentation on transactions and advisory locks.

I used Claude (Anthropic), an AI assistant, to help write the pipeline, the scenario runner, the synthetic-data generator, and the wording of this document. The logs in `docs/evidence/week7_synthetic/` come from a run on PostgreSQL 16.14 in the assistant's Linux environment, on synthetic files only. The question, scope, rules, and design decisions come from my approved proposal and my Week 4–6 work. I reviewed the generated material and I am responsible for the content.
