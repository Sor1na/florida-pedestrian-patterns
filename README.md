# Built for Cars, Deadly for Walkers

**Mining the roadway conditions behind Florida's pedestrian deaths, 2020–2024**

Yelysei Shkirpan · Capstone Project, B.S. Data Science · Eastern Florida State College · Fall 2026

**Central question (from the approved proposal):** *Which combinations of roadway class, posted speed limit, lighting, crossing location, and time of day most frequently characterize fatal pedestrian crashes on Florida's urban roads from 2020 through 2024, and which counties concentrate the most deaths under each pattern?*

**Audience:** safety planners at FDOT's State Safety Office and Florida MPOs who decide which FHWA proven countermeasures (lighting, crossings, medians, speed management) and which counties and corridor types to fund first.

This repository holds the capstone deliverables as they are built: the PostgreSQL database and data dictionary, the validated ETL pipeline, the analysis notebooks, and the dashboard.

| Week | Deliverable | Where |
|---|---|---|
| 7 | **Pipeline runs and recovery**: stage order with dependencies and six validation gates, a successful end-to-end run, a rerun with duplicate-prevention evidence, two deliberate failures, a killed run and its restart, logs with run ID / timestamps / row counts / errors, restart, recovery and rejected-record instructions | [`docs/Week7_Pipeline_Shkirpan.md`](docs/Week7_Pipeline_Shkirpan.md), [`pipeline/etl.py`](pipeline/etl.py), [`pipeline/run_scenarios.py`](pipeline/run_scenarios.py), [`docs/evidence/week7_synthetic/`](docs/evidence/week7_synthetic) |
| 6 | **Data cleaning plan**: measured profile of the raw FARS 2020–2024 and Census files, five quality issues with detection rules, actions, rationale and verification tests, bias statement, raw-preservation and logging plan | [`docs/Week6_Data_Cleaning_Plan_Shkirpan.pdf`](docs/Week6_Data_Cleaning_Plan_Shkirpan.pdf) ([Markdown](docs/Week6_Data_Cleaning_Plan_Shkirpan.md)), [`pipeline/profile_raw.py`](pipeline/profile_raw.py), [`docs/profile/`](docs/profile), [`tests/verify_cleaning_rules.sql`](tests/verify_cleaning_rules.sql) |
| 5 | **Database design**: conceptual and logical model, SQL scripts, data dictionary, constraint tests, sample queries | [`docs/Week5_Database_Design_Shkirpan.pdf`](docs/Week5_Database_Design_Shkirpan.pdf), [`sql/`](sql), [`tests/`](tests), [`queries/`](queries), [`docs/data_dictionary.md`](docs/data_dictionary.md) |
| 4 | First-pass conceptual data model | [the section below](#week-4-first-pass-conceptual-data-model), [`docs/Week4_Conceptual_Data_Model_Shkirpan.pdf`](docs/Week4_Conceptual_Data_Model_Shkirpan.pdf), commit `cd0e009` |

No real FARS rows are in this repository. FARS describes real deaths, and the proposal keeps person-level rows in the local database. Every record under `tests/` and `samples/`, and every input behind `docs/evidence/week7_synthetic/`, is synthetic. The repository holds no passwords, tokens, or keys; `.gitignore` keeps `.env` files, raw data, and database dumps out.

---

## Week 7: pipeline runs, reruns, failures, and recovery

The write-up is [`docs/Week7_Pipeline_Shkirpan.md`](docs/Week7_Pipeline_Shkirpan.md). The pipeline is one command:

```
pip install -r requirements.txt
createdb ped_safety
psql -d ped_safety -v ON_ERROR_STOP=1 -f sql/00_build_all.sql
python pipeline/etl.py run        # data/raw/ pinned by pipeline/sources.csv; safe to run again at any time
python pipeline/etl.py status     # the last runs, the steps of one run with row counts, failed checks, rejects
```

![Pipeline stages](docs/pipeline.png)

Eleven stages run in a fixed order (`python pipeline/etl.py stages`); six gates stop the run before anything is published: **G1** SHA-256 of every raw file against `pipeline/sources.csv`, **G2** required members and columns, **G3** Florida rows per file against the Week 6 profile, **G4** pandera record rules (unique keys, no orphans, code lists valid for the year, reference tables; failures go to the new table `rejected_record`), **G5** deaths and crashes per year against the published totals, **G6** post-load checks inside the load transaction, which commits only if they all pass. The load deletes and re-inserts 2020–2024 in that one transaction, so a rerun replaces rows instead of adding them, and a failure or a killed process leaves the tables as they were. Every run writes `etl_run`, `source_file`, `etl_log` (rows in and out per step), `validation_result` (one row per check) and `logs/run_NNNN.log` (timestamp, run ID, stage, row counts on every line).

`python pipeline/run_scenarios.py --synthetic` rebuilds the database and records six scenarios in [`docs/evidence/week7_synthetic/`](docs/evidence/week7_synthetic): first run, rerun (identical content fingerprint), a tampered raw file stopped by G1, four bad records quarantined by G4, a process killed inside the load, and the restart that recovers it. The committed evidence uses synthetic inputs in the exact FARS layout ([`tools/make_synthetic_raw.py`](tools/make_synthetic_raw.py)); without `--synthetic` the same scenarios run on the real files in `data/raw/` and write `docs/evidence/week7/` with case numbers masked.

---

## Week 6: data cleaning plan

The plan is [`docs/Week6_Data_Cleaning_Plan_Shkirpan.pdf`](docs/Week6_Data_Cleaning_Plan_Shkirpan.pdf) (Markdown source: [`docs/Week6_Data_Cleaning_Plan_Shkirpan.md`](docs/Week6_Data_Cleaning_Plan_Shkirpan.md)). Every number in it was measured on the raw files by one script:

```
# data/raw/ holds FARS2020..2024NationalCSV.zip and co-est2025-alldata.csv (not in Git; see the manifest)
python pipeline/profile_raw.py
```

It writes eleven tables to [`docs/profile/`](docs/profile) (manifest with SHA-256, inventory, unit of observation, column drift, variable profile, keys and duplicates, category frequencies, code drift, coordinates, missingness structure, Census profile), a readable summary in [`docs/profile/PROFILE.md`](docs/profile/PROFILE.md), and a run log in `docs/evidence/06_profile_run.log`. The raw zips are read in place and never modified.

Headline measurements: 3,736 pedestrian fatalities in 3,690 Florida crashes (695 / 819 / 780 / 774 / 668 by year), 3,053 of them in the urban, non-freeway population of the question; zero blank cells, zero duplicate or orphan rows, every STR_VEH link and every pbtype record present; 96% of case numbers reused across years; unknown body type in 57% of hit-and-run deaths vs 0.2% otherwise; posted speed unknown for 5.6% of striking vehicles; alcohol field unknown for 38.5% of deaths; RUR_URB not reported for 4.6% of the provisional 2024 deaths against at most 1.4% in the final years; coordinates usable for 99.9% of crashes.

The five issues the plan treats, in order of consequence: coded unknowns that are not random; the provisional 2024 Annual Report File; identity across years and multi-victim crashes (no deduplication); sparse and drifting code lists; and the derived block-group link. The post-load tests for all five are in [`tests/verify_cleaning_rules.sql`](tests/verify_cleaning_rules.sql); run against the Week 5 fixture they execute end to end ([`docs/evidence/07_verify_cleaning_rules_on_fixture.log`](docs/evidence/07_verify_cleaning_rules_on_fixture.log)).

---

## Week 5: database design

The full write-up is [`docs/Week5_Database_Design_Shkirpan.pdf`](docs/Week5_Database_Design_Shkirpan.pdf) (eight parts: question and scope, conceptual ER diagram, logical schema and normalization, physical implementation, data dictionary, test evidence, sample queries, rationale and limitations). This section is the short version.

### The model

![Conceptual ER diagram](docs/erd_conceptual.png)

Nine entities (source: [`docs/erd_conceptual.mmd`](docs/erd_conceptual.mmd)). The unit of observation is one pedestrian fatality, a row of `pedestrian`. The physical schema has 15 tables: the nine above, `code_lookup`, four pipeline tables (`etl_run`, `source_file`, `etl_log`, `validation_result`), and `data_dictionary`. Week 7 added a sixteenth, `rejected_record`, the quarantine of the record-level gate. Logical diagrams: [`docs/erd_logical.png`](docs/erd_logical.png) and [`docs/erd_logical_pipeline.png`](docs/erd_logical_pipeline.png).

### Build it and test it

Requirements: PostgreSQL 16 with `psql`. Python 3 only for the optional code-list check. Run everything from the repository root.

```
createdb ped_safety
psql -d ped_safety -v ON_ERROR_STOP=1 -f sql/00_build_all.sql
psql -d ped_safety -v ON_ERROR_STOP=1 -f tests/fixtures/valid_records.sql
psql -d ped_safety -f tests/test_constraints.sql
psql -d ped_safety -f queries/sample_queries.sql
python tests/check_code_domains.py
```

On Windows add `-U postgres` to each command (the installer creates that user and asks you to choose its password; it is typed at the prompt and never stored here). On macOS or Linux, `bash tests/run_all.sh` runs all of the above and rewrites the logs in `docs/evidence/`.

`00_build_all.sql` drops and recreates the `public` schema, so point it only at a database made for this project.

### What the tests show

`tests/test_constraints.sql` sends 56 statements to the database. For each invalid record the test names the SQLSTATE and the constraint that must reject it, so a test cannot pass by accident. Result on PostgreSQL 16.13: **56 tests, 56 passed, 0 failed** (49 invalid records rejected by the expected constraint, 7 valid edge cases accepted). Logs: [`docs/evidence/`](docs/evidence).

| Group | What it covers | Tests |
|---|---|---|
| A | keys: a crash is `year` + `st_case`; one typing record per pedestrian | A1–A6 |
| B | relationships: same-crash striking vehicle, mandatory county, optional block group, cascade on reload | B1–B14 |
| C | allowed values: FARS code lists, scope (Florida, 2020–2024, pedestrians, fatal), coordinates, reference data | C1–C26 |
| D | "one or more": a crash needs at least one pedestrian and one vehicle (checked at COMMIT) | D1–D4 |
| E | access control: the dashboard role reads aggregates only | E1–E6 |

### Files

```
sql/00_build_all.sql               one command: rebuilds everything in one transaction
sql/01_schema.sql                  16 tables (rejected_record added in Week 7), keys, NOT NULL, CHECK, EXCLUDE
sql/02_cardinality_triggers.sql    deferred triggers for the two "one or more" rules
sql/03_indexes.sql                 7 indexes beyond the 21 created by key constraints
sql/04_views.sql                   v_ped_transactions, v_county_rate, v_dash_pattern_county, 7 data-quality views
sql/05_roles.sql                   ped_etl, ped_analyst, ped_dashboard (NOLOGIN, no passwords)
sql/06_seed_county.sql             Florida's 67 counties
sql/07_seed_codes.sql              FARS code labels; PBCAT crash groups and types
sql/08_load_data_dictionary.sql    loads docs/data_dictionary.csv into the database
tests/fixtures/valid_records.sql   16 synthetic pedestrian deaths in 15 crashes
tests/test_constraints.sql         the 56 constraint tests
tests/check_code_domains.py        compares CHECK lists with code labels (no database needed)
tests/run_all.sh                   build + fixture + tests + queries, writes docs/evidence/
queries/sample_queries.sql         six queries tied to the project question
tools/export_data_dictionary.sql   writes docs/data_dictionary.md from the live database
docs/data_dictionary.csv / .md     the complete data dictionary (148 columns since Week 7)
docs/erd_conceptual.*              conceptual ER diagram (Mermaid source, SVG, PNG)
docs/erd_logical*.*                logical schema diagrams
docs/evidence/                     logs of the build, fixture load, tests, queries, code-list check
docs/Week5_Database_Design_Shkirpan.pdf / .docx   the design document
samples/, tests/check_samples.py, docs/erd.*      Week 4 files, kept as submitted
```

### Sources and AI assistance

Code lists come from the FARS Analytical User's Manuals (DOT HS 813 556, DOT HS 813 706) and the 2023 FARS/CRSS Pedestrian Bicyclist Crash Typing Manual (DOT HS 813 694); walkability classes and the meaning of `-99999` from EPA's National Walkability Index methodology and the Smart Location Database v3 documentation; population from the Census Bureau's Vintage 2025 county estimates. Full references are in the design document.

I used Claude (Anthropic), an AI assistant, to help draft the SQL scripts, the test harness, the data dictionary entries, and the wording of the documentation, and to check the code lists against the manuals. The logs in `docs/evidence/` come from a run on PostgreSQL 16.13 in the assistant's Linux environment. The question, scope, sources, and business rules come from my approved proposal and my Week 4 model. I reviewed the generated material and I am responsible for the content.

---

## Week 4: first-pass conceptual data model

Kept as submitted. The Week 5 design supersedes it in four places: `PED_CRASH_TYPE` no longer stores the crash group (`pedcgp` moved to the new `pbcat_type` table), `BLOCK_GROUP` has no geometry column, test record R1 uses `BODY_TYP` 34 instead of 31, and both reviewer questions in section 6 are now decided (see part 2 of the Week 5 document).

### Contents of this submission

1. [Unit of observation](#1-unit-of-observation)
2. [ER diagram](#2-er-diagram) — entities, keys, attributes, relationships, cardinality, optionality
3. [Business rules the diagram must preserve](#3-business-rules-the-diagram-must-preserve)
4. [Test records: three representative, two edge cases](#4-test-records)
5. [Rationale](#5-rationale)
6. [Questions for peer reviewers](#6-questions-for-peer-reviewers)

Supporting files: `docs/erd.mmd` (diagram source), `docs/erd.svg` and `docs/erd.png` (static copies), `samples/*.csv` (the test records), `tests/check_samples.py` (checks the business rules against the records), `docs/Week4_Conceptual_Data_Model_Shkirpan.pdf` (this page as a PDF).

---

### 1. Unit of observation

**One pedestrian fatality: a FARS person record coded as a pedestrian (PER_TYP = 5) with a fatal injury (INJ_SEV = 4) in a Florida crash from 2020 through 2024, linked to the crash it happened in, the vehicle that struck it, the county it happened in, and, when the coordinates are valid, the census block group around it.**

So the unit is the person, not the crash. A crash that kills two pedestrians produces two observations that share the same scene. The urban, non-freeway subset from the proposal (RUR_URB = 2, FUNC_SYS 3–7) is a filter on this unit, applied in the analysis view, not a different unit. County fatality rates are aggregates of it.

### 2. ER diagram

Crow's foot notation. The source is `docs/erd.mmd` (Mermaid); GitHub renders it below. Static copies: [`docs/erd.svg`](docs/erd.svg), [`docs/erd.png`](docs/erd.png).

```mermaid
erDiagram
    %% Notation: crow's foot. || exactly one, |o zero or one, }| one or more, }o zero or more.
    %% Solid line = identifying relationship (the child key contains the parent key).
    %% Dashed line = non-identifying relationship (plain foreign key).

    COUNTY ||--|{ COUNTY_POPULATION : "has a yearly estimate"
    COUNTY ||..o{ CRASH : "is the location of"
    COUNTY ||..|{ BLOCK_GROUP : "contains"
    CRASH }o..o| BLOCK_GROUP : "is geocoded to"
    CRASH ||--|{ PEDESTRIAN : "kills"
    CRASH ||--|{ VEHICLE : "involves"
    PEDESTRIAN }o..o| VEHICLE : "is struck by"
    PEDESTRIAN ||--o| PED_CRASH_TYPE : "is typed by"

    CRASH {
        int year PK "crash year 2020-2024"
        int st_case PK "12xxxx; reused every year"
        smallint county FK "GSA code = FIPS in Florida"
        text geoid10 FK "block group; NULL if no valid point"
        smallint month
        smallint day_week "1 = Sunday"
        smallint hour "0-23, 99 unknown"
        smallint rur_urb "2 = urban"
        smallint func_sys "3-7 kept, 1-2 excluded in view"
        smallint reljct2 "junction relation"
        smallint lgt_cond "light condition"
        smallint weather
        numeric latitude "NULL if 77.7777 / 88.8888 / 99.9999"
        numeric longitud "NULL if 777.7777 / 888.8888 / 999.9999"
        text tway_id "trafficway name, for corridor labels"
        smallint fatals "deaths in the crash"
        smallint peds "non-motorists in the crash"
    }

    VEHICLE {
        int year PK, FK
        int st_case PK, FK
        smallint veh_no PK "1-999; in-transport vehicles only"
        smallint body_typ "NCSA body type"
        smallint vspd_lim "posted mph; 0 none, 98/99 unknown"
        smallint hit_run "0 no, 1 yes"
    }

    PEDESTRIAN {
        int year PK, FK
        int st_case PK, FK
        smallint veh_no PK "always 0 for non-motorists"
        smallint per_no PK
        smallint str_veh FK "striking vehicle; NULL when 0"
        smallint per_typ "= 5 by scope"
        smallint inj_sev "= 4 by scope"
        smallint age "998/999 unknown"
        smallint sex
        smallint drinking "police-reported; stratifier only"
    }

    PED_CRASH_TYPE {
        int year PK, FK
        int st_case PK, FK
        smallint veh_no PK, FK
        smallint per_no PK, FK
        smallint pbcwalk "marked crosswalk present"
        smallint pbswalk "sidewalk present"
        smallint pedloc "at / near / not at intersection"
        smallint pedpos "position at impact"
        smallint pedctype "PBCAT crash type"
        smallint pedcgp "PBCAT crash group"
    }

    COUNTY {
        smallint county_fips PK "67 Florida counties"
        text name
    }

    COUNTY_POPULATION {
        smallint county_fips PK, FK
        smallint year PK
        int population "July 1 resident estimate"
        smallint vintage "Census vintage, e.g. 2025"
    }

    BLOCK_GROUP {
        text geoid10 PK "12-digit block group id"
        smallint county_fips FK "digits 3-5 of geoid10"
        numeric natwalkind "EPA walkability 1-20"
        numeric d3b "intersection density"
        numeric d4a "distance to transit; -99999 = none"
        int totpop
        geometry geom "block group polygon"
    }
```

**How to read the symbols.** `||` exactly one · `|o` zero or one · `}|` one or more · `}o` zero or more. The symbol next to an entity says how many of *that* entity take part for one instance of the other. A solid line is an identifying relationship: the child's key contains the parent's key. A dashed line is a non-identifying relationship: a plain foreign key. `PK` = part of the primary key, `FK` = foreign key.

#### Entities

| Entity | One row is… | Source | Identifier | Attributes kept in scope, and why |
|---|---|---|---|---|
| **CRASH** | one fatal crash in Florida, 2020–2024, with at least one pedestrian death | FARS *accident* file, STATE = 12 | `year` + `st_case` | `county`, `month`, `day_week`, `hour` (when and where); `rur_urb`, `func_sys`, `reljct2`, `lgt_cond`, `weather` (the scene conditions in the question); `latitude`, `longitud`, `geoid10` (the point, for the spatial join); `tway_id` (corridor label for the dashboard); `fatals`, `peds` (reconciliation counts) |
| **VEHICLE** | one motor vehicle in transport in that crash | FARS *vehicle* file | `year` + `st_case` + `veh_no` | `vspd_lim` (FARS records the posted speed limit per vehicle, for the road that vehicle was on), `body_typ`, `hit_run` |
| **PEDESTRIAN** | one person killed while walking (PER_TYP = 5, INJ_SEV = 4) — the unit of observation | FARS *person* file | `year` + `st_case` + `veh_no` (always 0) + `per_no` | `str_veh` (link to the striking vehicle), `age`, `sex`, `drinking` (stratifier only, never a rule antecedent); `per_typ`, `inj_sev` kept as scope checks |
| **PED_CRASH_TYPE** | the PBCAT crash-typing record for one pedestrian | FARS *pbtype* file | the same four columns as PEDESTRIAN | `pbcwalk`, `pbswalk`, `pedloc`, `pedpos`, `pedctype`, `pedcgp` (crossing location and what the pedestrian was doing) |
| **COUNTY** | one of Florida's 67 counties | Census FIPS; FARS county codes equal FIPS in Florida | `county_fips` | `name` |
| **COUNTY_POPULATION** | one July 1 resident estimate for one county in one year | Census Vintage 2025 estimates | `county_fips` + `year` | `population` (rate denominator), `vintage` (which Census release the number came from) |
| **BLOCK_GROUP** | one census block group with its walkability score | EPA Smart Location Database v3 / National Walkability Index | `geoid10` | `county_fips`, `natwalkind`, `d3b`, `d4a`, `totpop`, `geom` |

#### Relationships

| Relationship | Read left to right | Read right to left | Line | Why it is shaped this way |
|---|---|---|---|---|
| COUNTY — COUNTY_POPULATION | a county has one or more yearly estimates | an estimate belongs to exactly one county | identifying | rates need one denominator per county and year; normalized, so a new vintage or a sixth year adds rows, not columns |
| COUNTY — CRASH | a county is the location of zero or more crashes | a crash happened in exactly one county | non-identifying | mandatory: every death must land in a county rate; a county with zero deaths still exists (rate 0, unstable flag) |
| COUNTY — BLOCK_GROUP | a county contains one or more block groups | a block group lies in exactly one county | non-identifying | lets walkability be aggregated to the county when a crash cannot be geocoded |
| CRASH — BLOCK_GROUP | a crash is geocoded to zero or one block group | a block group contains zero or more crash points | non-identifying | optional because coordinates are sometimes missing; the link is derived by a spatial join, it is not in FARS |
| CRASH — PEDESTRIAN | a crash kills one or more pedestrians | a pedestrian died in exactly one crash | identifying | only crashes with a pedestrian death are loaded, hence "one or more" |
| CRASH — VEHICLE | a crash involves one or more in-transport vehicles | a vehicle belongs to exactly one crash | identifying | FARS only records crashes that involve at least one motor vehicle in transport |
| PEDESTRIAN — VEHICLE | a pedestrian is struck by zero or one vehicle | a vehicle strikes zero or more pedestrians | non-identifying | the FARS code list allows STR_VEH = 0 ("not applicable"), and FARS records only one striking vehicle per non-motorist |
| PEDESTRIAN — PED_CRASH_TYPE | a pedestrian is typed by zero or one crash-typing record | a typing record belongs to exactly one pedestrian | identifying | the manual defines one PBTYPE record per pedestrian; kept optional so a missing record is a validation warning, not a load failure |

#### Left out on purpose

- `code_lookup` (variable, code, label, year_from, year_to). Every coded column points to it, so drawing it would add a line to every entity. It belongs to the physical schema and the data dictionary.
- `etl_log`, `validation_result`, and the download manifest. They describe the pipeline, not the deaths.
- Parked and working vehicles (the FARS *parkwork* file). Not loaded in the first pass; a pedestrian whose STR_VEH names such a vehicle gets an empty striking-vehicle link (rule 2).
- Drivers and passengers in the same crashes. See reviewer question 1.
- RACE and HISPANIC. Excluded by the proposal's ethics section.
- `v_ped_transactions`. A view, not an entity: one row per pedestrian after the urban, non-freeway filter, with every attribute discretized into items.

### 3. Business rules the diagram must preserve

**Rule 1 — Identity survives across years.** A crash is identified by `year` and `st_case` together, because FARS reuses case numbers every year (Florida cases are 12xxxx in every file). Every vehicle, pedestrian, and crash-typing record carries the same `year` and `st_case` as its crash, so a record can never attach to a crash from another year. In the diagram both columns are `PK, FK` in all three child entities, joined by solid identifying lines. Tested by R1 and R2, which share `st_case` 120417 in 2021 and 2023 and stay separate crashes.

**Rule 2 — A pedestrian has at most one striking vehicle, and it must be an in-transport vehicle of the same crash.** `str_veh` is either empty or equal to a `veh_no` that exists under the same `year` and `st_case`. STR_VEH = 0 ("not applicable") or a number with no matching in-transport vehicle leaves the link empty; the pedestrian row stays, and its vehicle-side items (speed limit, body type, hit-and-run) become "unknown" in the analysis view. A vehicle may strike zero, one, or several pedestrians. In the diagram: `|o` beside VEHICLE, `}o` beside PEDESTRIAN, dashed line. This refines the proposal's Objective 1 check from "every pedestrian links to a striking vehicle" to "every non-zero STR_VEH resolves to a vehicle in the same crash".

**Rule 3 — Place is known at two levels, one mandatory and one optional.** Every crash has exactly one county, and that county must be one of the 67 rows in COUNTY; the FARS codes 0, 997, 998, and 999 fail validation. A crash links to at most one block group, and only when its coordinates are valid (the codes 77.7777, 88.8888, 99.9999 and their longitude equivalents become NULL) and the point falls inside a Florida block group. A crash with no block group still counts in its county's rate. In the diagram: `||` beside COUNTY on the crash line, `|o` beside BLOCK_GROUP.

### 4. Test records

All five records are synthetic. They follow the real code lists (FARS Analytical User's Manual, the FARS/CRSS pedestrian crash-typing manual, EPA SLD, Census) so they look like real rows, but none is copied from FARS. This is on purpose: FARS describes real deaths, the proposal promises that person-level rows stay in the local database, and a public repository is not the place for them. Population and walkability values are placeholders in a realistic range; the real Vintage 2025 and EPA values are loaded in Week 6.

Each record is one pedestrian fatality with all of its related rows. The same rows are in `samples/*.csv`, and `tests/check_samples.py` checks the three business rules against them (output at the end of this section).

#### R1 — The archetype: dark, unlit arterial, mid-block

Friday, 9 p.m., November. A principal arterial (US-192) posted 45 mph, dark and not lighted, away from any junction, no marked crosswalk and no sidewalk, in Brevard County. A pickup strikes a 47-year-old man crossing the road. This is the pattern the question expects to find most often, and every link in the model is present: crash → county, crash → block group, pedestrian → striking vehicle, pedestrian → crash type.

| Entity | Key | Values |
|---|---|---|
| CRASH | (2021, 120417) | county = 9, geoid10 = 120090651021, month = 11, day_week = 6, hour = 21, rur_urb = 2, func_sys = 3, reljct2 = 1, lgt_cond = 2, weather = 1, latitude = 28.0791, longitud = -80.6752, tway_id = US-192, fatals = 1, peds = 1 |
| VEHICLE | (2021, 120417, veh_no 1) | body_typ = 31, vspd_lim = 45, hit_run = 0 |
| PEDESTRIAN | (2021, 120417, 0, per_no 1) | str_veh = 1, per_typ = 5, inj_sev = 4, age = 47, sex = 1, drinking = 0 |
| PED_CRASH_TYPE | (2021, 120417, 0, per_no 1) | pbcwalk = 0, pbswalk = 0, pedloc = 3, pedpos = 3, pedctype = 760, pedcgp = 750 |
| COUNTY / COUNTY_POPULATION | county_fips 9 / (9, 2021) | name = Brevard; population 2021 = 616,000 (vintage 2025) |
| BLOCK_GROUP | geoid10 120090651021 | county_fips = 9, natwalkind = 7.17, d3b = 41.3, d4a = -99999, totpop = 1842 |

#### R2 — Intersection, lighted, turning vehicle

Wednesday, 6 p.m., January. A minor arterial posted 35 mph, dark but lighted, at an intersection with a marked crosswalk and sidewalks, in Miami-Dade County. A sedan turning left strikes a 72-year-old woman in the crosswalk area. This calls for a different countermeasure family (crossing visibility, turn conflicts) and shows that crossing location lives on PED_CRASH_TYPE, lighting on CRASH, and speed on VEHICLE. It shares `st_case` 120417 with R1; only the year keeps them apart (rule 1).

| Entity | Key | Values |
|---|---|---|
| CRASH | (2023, 120417) | county = 86, geoid10 = 120860042001, month = 1, day_week = 4, hour = 18, rur_urb = 2, func_sys = 4, reljct2 = 2, lgt_cond = 3, weather = 1, latitude = 25.8012, longitud = -80.2401, tway_id = NW 27TH AVE, fatals = 1, peds = 1 |
| VEHICLE | (2023, 120417, veh_no 1) | body_typ = 4, vspd_lim = 35, hit_run = 0 |
| PEDESTRIAN | (2023, 120417, 0, per_no 1) | str_veh = 1, per_typ = 5, inj_sev = 4, age = 72, sex = 2, drinking = 0 |
| PED_CRASH_TYPE | (2023, 120417, 0, per_no 1) | pbcwalk = 1, pbswalk = 1, pedloc = 1, pedpos = 2, pedctype = 781, pedcgp = 790 |
| COUNTY / COUNTY_POPULATION | county_fips 86 / (86, 2023) | name = Miami-Dade; population 2023 = 2,720,000 (vintage 2025) |
| BLOCK_GROUP | geoid10 120860042001 | county_fips = 86, natwalkind = 14.83, d3b = 168.9, d4a = 412.5, totpop = 2105 |

#### R3 — Walking along the road, no sidewalk

Tuesday, 5 a.m., March, rain. A major collector posted 30 mph, dark and not lighted, in Duval County. A compact SUV strikes a 34-year-old man walking on the paved shoulder, from behind. Covers the 400-series crash group and shows an unknown code kept as a value rather than dropped (`drinking` = 9, unknown).

| Entity | Key | Values |
|---|---|---|
| CRASH | (2022, 121088) | county = 31, geoid10 = 120310144022, month = 3, day_week = 3, hour = 5, rur_urb = 2, func_sys = 5, reljct2 = 1, lgt_cond = 2, weather = 2, latitude = 30.3312, longitud = -81.6560, tway_id = MONCRIEF RD, fatals = 1, peds = 1 |
| VEHICLE | (2022, 121088, veh_no 1) | body_typ = 14, vspd_lim = 30, hit_run = 0 |
| PEDESTRIAN | (2022, 121088, 0, per_no 1) | str_veh = 1, per_typ = 5, inj_sev = 4, age = 34, sex = 1, drinking = 9 |
| PED_CRASH_TYPE | (2022, 121088, 0, per_no 1) | pbcwalk = 0, pbswalk = 0, pedloc = 3, pedpos = 4, pedctype = 410, pedcgp = 400 |
| COUNTY / COUNTY_POPULATION | county_fips 31 / (31, 2022) | name = Duval; population 2022 = 1,016,000 (vintage 2025) |
| BLOCK_GROUP | geoid10 120310144022 | county_fips = 31, natwalkind = 5.50, d3b = 22.7, d4a = -99999, totpop = 1310 |

#### E1 — Edge case: one crash, two deaths (2024 Annual Report File)

Saturday, 11 p.m., July. A lighted principal arterial (US-441) posted 45 mph, mid-block, in Orange County. A large SUV strikes two people crossing together; both die. Tests that CRASH is one-to-many with PEDESTRIAN, that one VEHICLE can strike two pedestrians, that one scene becomes two transactions, that the county count rises by two, and that `fatals` = `peds` = 2 is available for the reconciliation check. The year is 2024, so the row comes from the Annual Report File and may change in the Final file; the reload must replace it, not duplicate it, which the composite key guarantees.

| Entity | Key | Values |
|---|---|---|
| CRASH | (2024, 120078) | county = 95, geoid10 = 120950145032, month = 7, day_week = 7, hour = 23, rur_urb = 2, func_sys = 3, reljct2 = 1, lgt_cond = 3, weather = 1, latitude = 28.4912, longitud = -81.4005, tway_id = US-441, fatals = 2, peds = 2 |
| VEHICLE | (2024, 120078, veh_no 1) | body_typ = 15, vspd_lim = 45, hit_run = 0 |
| PEDESTRIAN | (2024, 120078, 0, per_no 1) | str_veh = 1, per_typ = 5, inj_sev = 4, age = 29, sex = 1, drinking = 1 |
| PEDESTRIAN | (2024, 120078, 0, per_no 2) | str_veh = 1, per_typ = 5, inj_sev = 4, age = 26, sex = 2, drinking = 8 |
| PED_CRASH_TYPE | (2024, 120078, 0, per_no 1) | pbcwalk = 0, pbswalk = 1, pedloc = 3, pedpos = 3, pedctype = 770, pedcgp = 750 |
| PED_CRASH_TYPE | (2024, 120078, 0, per_no 2) | pbcwalk = 0, pbswalk = 1, pedloc = 3, pedpos = 3, pedctype = 770, pedcgp = 750 |
| COUNTY / COUNTY_POPULATION | county_fips 95 / (95, 2024) | name = Orange; population 2024 = 1,500,000 (vintage 2025) |
| BLOCK_GROUP | geoid10 120950145032 | county_fips = 95, natwalkind = 10.67, d3b = 95.4, d4a = 780.0, totpop = 2960 |

#### E2 — Edge case: hit-and-run with no coordinates

Sunday, 2 a.m., September. A principal arterial (SR-60) posted 40 mph, dark and not lighted, in Hillsborough County. The vehicle left the scene, so its body type is unknown (99), but the posted speed limit is known because the road is. Latitude and longitude were not reported (77.7777 / 777.7777), so they become NULL and there is no block group. Tests the optional side of CRASH — BLOCK_GROUP (the walkability item becomes "unknown" while the death still counts in the county rate), that `hit_run` = 1 and `body_typ` = 99 are kept as values, and that the striking-vehicle link survives even when almost nothing is known about the vehicle.

| Entity | Key | Values |
|---|---|---|
| CRASH | (2022, 121307) | county = 57, geoid10 = NULL, month = 9, day_week = 1, hour = 2, rur_urb = 2, func_sys = 3, reljct2 = 1, lgt_cond = 2, weather = 1, latitude = NULL, longitud = NULL, tway_id = SR-60, fatals = 1, peds = 1 |
| VEHICLE | (2022, 121307, veh_no 1) | body_typ = 99, vspd_lim = 40, hit_run = 1 |
| PEDESTRIAN | (2022, 121307, 0, per_no 1) | str_veh = 1, per_typ = 5, inj_sev = 4, age = 58, sex = 1, drinking = 1 |
| PED_CRASH_TYPE | (2022, 121307, 0, per_no 1) | pbcwalk = 0, pbswalk = 0, pedloc = 3, pedpos = 3, pedctype = 620, pedcgp = 600 |
| COUNTY / COUNTY_POPULATION | county_fips 57 / (57, 2022) | name = Hillsborough; population 2022 = 1,513,000 (vintage 2025) |
| BLOCK_GROUP | — | no row: coordinates not reported, so no spatial join |

#### Running the check

```
$ python tests/check_samples.py
```

```
Identifiers
  PASS  crash: composite key is unique
  PASS  vehicle: composite key is unique
  PASS  pedestrian: composite key is unique
  PASS  ped_crash_type: composite key is unique
  note  st_case reused across years, distinct crashes only because year is in the key: {'120417': ['2021', '2023']}
Rule 1 - one crash, identified by year + st_case, for every dependent record
  PASS  every vehicle row belongs to an existing crash
  PASS  every pedestrian row belongs to an existing crash
  PASS  every ped_crash_type row belongs to an existing crash
  PASS  every ped_crash_type row belongs to an existing pedestrian
  PASS  at most one ped_crash_type row per pedestrian
Rule 2 - at most one striking vehicle, and it must be an in-transport vehicle of the same crash
  PASS  str_veh is empty/0 or points to a vehicle in the same crash
  PASS  pedestrian rows are non-motorists (veh_no 0) coded pedestrian (5) and fatal (4)
  PASS  every crash has at least one in-transport vehicle
  PASS  every crash has at least one pedestrian fatality
  note  crashes with more than one pedestrian fatality (each death is its own row/transaction): {('2024', '120078'): 2}
Rule 3 - county is mandatory and known; block group is optional and only with valid coordinates
  PASS  every crash has a county that exists in the county table
  PASS  a block group is present only with valid coordinates and exists in block_group
  PASS  every county has a population estimate for every year 2020-2024
  PASS  every block group belongs to an existing county and its geoid encodes that county
  note  crashes with no block group (kept; they still count in county rates): [('2022', '121307')]
  note  counties with zero sample crashes (allowed; rate = 0 with an unstable flag): ['67']
Unknown codes kept as values, not dropped
  note  vehicle ('2022', '121307', '1') body_typ=99
  note  pedestrian ('2022', '121088', '1') drinking=9
  note  pedestrian ('2024', '120078', '2') drinking=8
  note  block_group 120090651021 d4a=-99999 (no transit; treat as NULL)
  note  block_group 120310144022 d4a=-99999 (no transit; treat as NULL)

All rules hold for the five sample records.
```

`python tests/check_samples.py --negative` adds three broken rows in memory (a vehicle with no crash, a pedestrian whose `str_veh` points to a vehicle that does not exist, a crash with county 999) and shows each rule failing.

### 5. Rationale

The central question asks which combinations of road class, posted speed, lighting, crossing location, and time of day recur in fatal pedestrian crashes on Florida's urban roads, and which counties concentrate them. The model puts each of those items on the entity where FARS actually records it, so that all of them can be pulled onto one row per death for the association mining.

The unit is the pedestrian, not the crash. Deaths are what planners count, and one crash can kill two people under the same conditions. That is why PEDESTRIAN carries the fatality and CRASH stays a parent. Light condition, junction relation, road class, and hour describe the scene, so they live on CRASH. The posted speed limit is a property of the road the striking vehicle was on, and FARS records it per vehicle; the "is struck by" relationship is what lets each death borrow the speed limit, body type, and hit-and-run flag of the vehicle that hit it. Crosswalk presence, position, and crash type come from the PBTYPE file and answer the crossing-location part of the question.

The "where" needs two levels. COUNTY and COUNTY_POPULATION give the denominators for the five-year rates and the county dashboard. BLOCK_GROUP adds the EPA walkability score. County is mandatory because every county rate must include every death. Block group is optional because coordinates are sometimes missing, and dropping those deaths would bias the rates.

Composite keys (year plus st_case) exist because FARS reuses case numbers every year. Unknown codes stay as values instead of being dropped, since "speed limit unknown" is itself something a planner should see. Left out on purpose are the code lookup, ETL log, and validation tables from the proposal: they describe the pipeline, not the deaths.

*(290 words)*

### 6. Questions for peer reviewers

1. **How wide should PEDESTRIAN be?** Right now it holds only the people who died, about 3,700 rows. Loading every person in those crashes (mostly drivers) would let me attach driver age and impairment to each pattern later, but it roughly triples the person rows and adds attributes the question does not ask about. Would you keep the entity narrow, or widen it to a general PERSON now, while the schema is still cheap to change?

2. **Where should the crash → block group link live?** It comes from a spatial join I run, not from FARS. I show it as a nullable `geoid10` on CRASH. The proposal had a separate `crash_blockgroup` table instead. Would you rather see the separate table, which can record the join method, boundary vintage, and date, or is a nullable key plus a note in the data dictionary enough?

### Sources for the code definitions

- National Highway Traffic Safety Administration. (2026). *Manuals for FARS: Analytical user's manual 1975–2024, FARS/CRSS 2024 coding and validation manual, and pedestrian bicyclist crash typing manual*. U.S. Department of Transportation. https://static.nhtsa.gov/nhtsa/downloads/FARS/Links%20for%20FARS%20Manuals.pdf
- National Highway Traffic Safety Administration. (2025). *2023 FARS/CRSS pedestrian bicyclist crash typing manual* (Report No. DOT HS 813 694). U.S. Department of Transportation. https://crashstats.nhtsa.dot.gov/Api/Public/ViewPublication/813694
- U.S. Environmental Protection Agency. (2021). *National Walkability Index: Methodology and user guide*. https://www.epa.gov/sites/default/files/2021-06/documents/national_walkability_index_methodology_and_user_guide_june2021.pdf
- U.S. Census Bureau. (2026). *County population totals and components of change: 2020–2025 (Vintage 2025)*. https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html
