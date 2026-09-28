# Week 6: Evidence-Based Data Cleaning Plan

**Built for Cars, Deadly for Walkers: mining the roadway conditions behind Florida's pedestrian deaths, 2020–2024**

Yelysei Shkirpan · Capstone Project, B.S. Data Science · Eastern Florida State College · September 27, 2026

Repository: https://github.com/Sor1na/florida-pedestrian-patterns

**Purpose.** This document fixes the cleaning rules before any raw value is transformed. Every number in it was measured on the raw files by one script, `pipeline/profile_raw.py`, which reads the downloaded zips in place and writes its tables to `docs/profile/`. Nothing in `data/raw/` was modified. To re-derive the evidence:

```
python pipeline/profile_raw.py        # writes docs/profile/*.csv, docs/profile/PROFILE.md, docs/evidence/06_profile_run.log
```

The plan follows the data-quality vocabulary of the course textbook (Tan, Steinbach, Karpatne & Kumar, *Introduction to Data Mining*, 2nd ed., 2019): attribute types (section 2.1), measurement and collection errors, missing values, inconsistent values and duplicates (section 2.2), and the preprocessing operations that the rules use, aggregation, feature creation, discretization and binarization (section 2.3). Where the book offers a choice, for example the three ways of handling missing values in 2.2.1 (eliminate, estimate, or ignore during analysis), the plan says which one is taken and why, in terms of the project question.

**Project question (from the approved proposal).** Which combinations of roadway class, posted speed limit, lighting, crossing location, and time of day most frequently characterize fatal pedestrian crashes on Florida's urban roads from 2020 through 2024, and which counties concentrate the most deaths under each pattern?

---

## 1. Sources, extraction, counts, and unit of observation

### 1.1 What was downloaded

| Source | Publisher, release | Extracted | Files | Size | SHA-256 (first 12) |
|---|---|---|---|---|---|
| FARS 2020 National CSV | NHTSA, Final file | 2026-09-27 | 1 zip, 34 CSV members | 31.0 MB | `b2806902b3da` |
| FARS 2021 National CSV | NHTSA, Final file | 2026-09-27 | 1 zip, 34 CSV members | 35.2 MB | `743c19a13884` |
| FARS 2022 National CSV | NHTSA, Final file | 2026-09-27 | 1 zip, 34 CSV members | 34.7 MB | `989448d7a2f3` |
| FARS 2023 National CSV | NHTSA, Final file | 2026-09-27 | 1 zip, 34 CSV members | 34.2 MB | `edde841eb493` |
| FARS 2024 National CSV | NHTSA, **Annual Report File (provisional)** | 2026-09-27 | 1 zip, 34 CSV members | 32.7 MB | `5112727a8c0d` |
| Census county population | U.S. Census Bureau, Vintage 2025 (`co-est2025-alldata.csv`) | 2026-09-27 | 1 CSV, 3,195 rows × 99 columns | 2.1 MB | `4f5a499d851e` |
| EPA Smart Location Database v3 / National Walkability Index | U.S. EPA, May 2021 | **not yet downloaded** | 1 file geodatabase (about 1 GB) | — | — |

Full checksums and URLs: `docs/profile/00_manifest_sha256.csv`. The EPA file is needed only for the block-group spatial join in Week 7; its rules below (issue 5) come from the EPA methodology and the SLD data dictionary, not from a measured profile, and they are marked as such.

### 1.2 Tables and rows

Of the 34 members in each FARS zip, the project loads five. The table gives national and Florida (STATE = 12) row counts as read, before any filter other than state.

| FARS file | 2020 | 2021 | 2022 | 2023 | 2024 | Florida total | Columns |
|---|---|---|---|---|---|---|---|
| accident (national) | 35,935 | 39,785 | 39,422 | 37,769 | 36,297 | — | 80–81 |
| **accident (Florida)** | 3,097 | 3,453 | 3,315 | 3,163 | 2,931 | **15,959** | |
| vehicle (Florida) | 4,845 | 5,485 | 5,234 | 5,019 | 4,620 | 25,203 | 201–203 |
| person (Florida) | 7,785 | 8,889 | 8,592 | 8,222 | 7,645 | 41,133 | 126 |
| pbtype (Florida) | 936 | 1,102 | 1,100 | 1,085 | 970 | 5,193 | 45 |
| parkwork (Florida) | 93 | 121 | 119 | 113 | 121 | 567 | 115 |

Source: `docs/profile/01_inventory.csv`. Encodings are not uniform: the 2020 accident, pbtype, and parkwork files decode only as cp1252 (non-ASCII bytes in the `TWAY_ID` free text), the other 22 files as UTF-8, and the Census file as latin-1 (`Doña Ana` in another state). The loader therefore tries UTF-8 first and falls back to cp1252, and records the encoding used. No file contained a blank cell in any in-scope column (`04_variable_profile.csv`, column `blank_cells` = 0 for every variable and year).

### 1.3 Unit of observation

One row of the analysis is **one pedestrian fatality**: a FARS person record with PER_TYP = 5 (pedestrian) and INJ_SEV = 4 (fatal injury) in a Florida crash, 2020–2024. It is the person, not the crash, because deaths are what planners count and one crash can kill more than one person under the same conditions.

| Measured on the raw files | 2020 | 2021 | 2022 | 2023 | 2024 | Total |
|---|---|---|---|---|---|---|
| All deaths in Florida fatal crashes (INJ_SEV = 4) | 3,329 | 3,741 | 3,548 | 3,375 | 3,138 | 17,131 |
| Pedestrian rows, any injury (PER_TYP = 5) | 739 | 867 | 847 | 815 | 713 | 3,981 |
| **Pedestrian fatalities (the unit)** | **695** | **819** | **780** | **774** | **668** | **3,736** |
| Crashes with at least one pedestrian fatality | 689 | 809 | 768 | 768 | 656 | 3,690 |
| Crashes with two or more pedestrian fatalities (max per crash) | 6 (2) | 8 (4) | 12 (2) | 6 (2) | 10 (3) | 42 |
| … of which urban (RUR_URB = 2) | 635 | 746 | 709 | 671 | 564 | 3,325 |
| … of which **urban and not a freeway (FUNC_SYS 3–7): the analysis population** | 588 | 674 | 644 | 625 | 522 | **3,053** |
| … urban freeway or interstate (FUNC_SYS 1–2), excluded by the proposal | 47 | 72 | 65 | 46 | 42 | 272 |
| … rural (RUR_URB = 1), excluded by the proposal | 59 | 72 | 68 | 92 | 73 | 364 |
| … RUR_URB not reported or unknown (6, 8, 9) | 1 | 1 | 3 | 11 | 31 | 47 |

Source: `docs/profile/02_unit_of_observation.csv`. The proposal estimated "about 3,700" deaths; the measured count is 3,736, of which 3,053 (81.7%) fall inside the urban, non-freeway population that the question is about. The remaining 683 stay in the database and in the county rates; section 5 discusses what their exclusion from the pattern mining means.

---

## 2. Profile

### 2.1 Attribute types and ranges

FARS stores every attribute as an integer code, so pandas would read them all as one type. The type that matters for mining is the semantic one (Tan et al., section 2.1). The profile classifies each in-scope variable, and the measured range confirms that no value falls outside the FARS code list.

| Variable (file) | Semantic type | Role in the question | Observed valid range | Unknown / filler codes seen |
|---|---|---|---|---|
| LGT_COND (accident) | nominal | lighting | 1–5 | 6, 7, 8, 9 |
| FUNC_SYS (accident) | ordinal (road hierarchy) | roadway class | 1–7 | 96, 98 |
| RUR_URB (accident) | nominal | population filter | 1–2 | 6, 8, 9 |
| HOUR (accident) | ordinal, cyclic | time of day | 0–23 | none (99 never occurs) |
| DAY_WEEK, MONTH (accident) | ordinal, cyclic | time of day, stability | 1–7, 1–12 | none |
| RELJCT2 (accident) | nominal | crossing location (crash level) | 1–20 | 98, 99 |
| WEATHER (accident) | nominal | stratifier | 1–10 | 99 (from 2022) |
| LATITUDE, LONGITUD (accident) | interval (coordinates) | block-group join | 24.56–31.00, −87.41 to −80.04 | 77.7777 / 777.7777 fillers, 3 crashes |
| COUNTY (accident) | nominal | county rates | 1–133, all 67 valid FIPS | none |
| VSPD_LIM (vehicle, striking vehicle) | ratio, mph | posted speed | 0–70, all multiples of 5 | 98, 99 |
| BODY_TYP (vehicle) | nominal | vehicle class | 37 distinct codes | 98, 99 |
| HIT_RUN (vehicle) | binary | stratifier | 0–1 | none |
| STR_VEH (person) | link to vehicle | joins speed to death | 1–5 | 0 never occurs |
| AGE (person) | ratio, years | stratifier | 0–98 | 998, 999 |
| SEX, DRINKING (person) | nominal | stratifiers | 1–2, 0–1 | 8, 9 |
| PEDLOC, PEDPOS (pbtype) | nominal | crossing location | 1–4, 1–8 | 9 |
| PBCWALK, PBSWALK (pbtype) | binary | crossing location | 0–1 | 9 (3 rows) |
| PEDCTYPE, PEDCGP (pbtype) | nominal (PBCAT) | crossing behaviour | 48 and 16 distinct codes | 990 group, 600 group |

Source: `docs/profile/04_variable_profile.csv`.

### 2.2 Missingness: two kinds, measured separately

There are no empty cells. All missingness in FARS is **coded**: a value such as 99 that carries a documented meaning ("unknown") but no information about the attribute. The profile counts these codes per variable and year (`04_variable_profile.csv`) and then asks *why* they are missing (`08b_missingness_structure_consistency.csv`). The second question is the one that decides the rule.

| Variable | Coded unknown, pooled 2020–2024 | Range across years | Structure found |
|---|---|---|---|
| DRINKING (8, 9) | 1,439 of 3,736 (38.5%) | 34.4% → 43.0%, rising | police-reported field; unknown share grew every year after 2022 |
| PEDCGP crash group: 990 "insufficient details" | 494 (13.2%) | 11.5%–14.8% | plus 563 (15.1%) coded 600 "pedestrian in roadway, circumstances unknown"; together 28.3% of deaths have no usable crash type, while PEDLOC is unknown for only 4 |
| BODY_TYP (98, 99) | 405 (10.8%) | 10.2%–11.9% | **57.4% when the driver left the scene (400 of 697), 0.16% otherwise (5 of 3,039)** |
| VSPD_LIM (98, 99) | 207 of 3,690 striking vehicles (5.6%) | 4.5%–6.3% | 18.5% for hit-and-run vs 2.6% otherwise; 4.2%–7.5% on urban road classes, 0% on interstates |
| AGE (998, 999) | 214 (5.7%) | 3.9%–6.5% | — |
| SEX (8, 9) | 160 (4.3%) | 2.8%–5.6% | — |
| LGT_COND (6, 7, 8, 9) | 69 (1.9%) | 1.0%–3.2% | 54 of the 69 are code 6 "dark, unknown lighting": the pedestrian died in the dark, only the street-light status is unknown |
| PEDPOS (9) | 70 (1.9%) | 0.6%–2.7% | — |
| RUR_URB (6, 8, 9) | 47 (1.3%) | 0.1% → **4.6% in 2024** | 31 of the 47 are in the provisional 2024 file |
| FUNC_SYS (96, 98) | 14 (0.4%) | 0.1%–0.8% | 12 are code 96 "not in state inventory", measured to be the same 12 crashes as RUR_URB 6 |
| RELJCT2 (98, 99), PEDLOC (9), PBSWALK (9) | 6, 4, 3 | — | negligible |
| HOUR, DAY_WEEK, MONTH, COUNTY, HIT_RUN, PBCWALK, STR_VEH | 0 | — | complete |

Two consistency tests that Tan et al. (2.2.1) recommend for detecting inconsistent values found nothing: no death is coded "daylight" between 22:00 and 04:59, and none is coded "dark" between 10:00 and 15:59. Coordinates are complete to eight decimals for 3,687 of 3,690 crashes (99.9%), all inside Florida's bounding box; two crashes in 2020 share an identical point.

### 2.3 Duplicates and keys

| Check (per year, Florida rows) | Result |
|---|---|
| ST_CASE unique within accident; (ST_CASE, VEH_NO) unique within vehicle; (ST_CASE, VEH_NO, PER_NO) unique within person and pbtype | 0 violations in every year |
| Exact duplicate rows in accident or pbtype | 0 |
| Vehicle, person, or pbtype rows whose ST_CASE is not in accident (orphans) | 0 |
| Pedestrian fatalities without a pbtype record | 0 of 3,736 |
| pbtype person type (PBPTYPE) disagreeing with person PER_TYP | 0 |
| STR_VEH resolving to an in-transport vehicle of the same crash | **3,736 of 3,736** (0 point to a parked vehicle, 0 are code 0) |
| accident.FATALS equal to the count of INJ_SEV = 4 person rows | equal in all 3,690 crashes |
| accident.PEDS equal to the count of non-motorist person rows | equal in all 3,690 crashes |
| **ST_CASE reused across years** | **3,503 of 3,639 distinct Florida case numbers appear in more than one year (up to all five)** |
| Crashes with two or more pedestrian deaths | 42 crashes, 88 deaths, sharing every crash-level attribute |

Source: `docs/profile/05_keys_duplicates_consistency.csv`, `05b_st_case_reuse.csv`. Interpretation: within a year the files are clean and fully linked, so the plan contains **no deduplication step**. The two things that look like duplication are not: case numbers recur because FARS restarts them every year, and multi-victim crashes produce several legitimate rows with identical scene attributes. Both are handled by the key design (issue 3), not by dropping rows.

### 2.4 Category frequencies, pooled 2020–2024 (all 3,736 deaths)

Lighting: dark-lighted 44.7%, dark-not-lighted 31.9%, daylight 17.2%, dawn/dusk 4.4%, unknown group 1.9%. Roadway class: principal arterial 45.9%, minor arterial 22.7%, major collector 10.6%, local 10.1%, interstate 6.6%, minor collector 1.9%, freeway 1.8%. Posted speed of the striking vehicle's road: 45–50 mph 37.9%, 35–40 mph 25.5%, 55 mph and above 18.0%, 30 mph and below 12.5%, not reported/unknown 5.6%, no statutory limit 0.5%. Time of day: 18:00–20:59 27.2%, 21:00–23:59 25.8%, 00:00–05:59 24.3%, 06:00–11:59 12.9%, 12:00–17:59 9.8%. Junction relation: non-junction 71.2%, intersection-related 20.5%, at intersection 4.9%. Pedestrian location: not at intersection 75.6%, at intersection 15.4%, intersection-related 8.3%. Position: travel lane 74.4%, crosswalk area 11.5%, intersection area 4.8%. Marked crosswalk present 13.1%; sidewalk present 28.8%. Striking vehicle: 4-door sedan 30.8%, light pickup 14.7%, compact SUV 14.5%, unknown 10.8%, large SUV 6.1%; hit-and-run 18.7%. Age: 45–64 33.2%, 25–44 29.5%, 65+ 22.5%, 15–24 6.9%, unknown 5.7%, 0–14 2.2%. Sex: male 67.7%, female 28.0%, unknown 4.3%.

Counties: 64 of 67 counties recorded at least one pedestrian death; the ten largest counties account for 63.9% of deaths (Miami-Dade 12.0%, Broward 9.7%, Hillsborough 7.6%, Palm Beach 7.1%, Orange 7.1%, Duval 5.7%, Pinellas 5.0%, Polk 3.3%, Pasco 3.3%, Lee 3.3%); 33 counties have fewer than 20 deaths in five years. Full tables: `docs/profile/06_category_frequencies.csv` (by year and pooled).

### 2.5 Drift between years

Nineteen columns appear in some years only (`03_column_drift.csv`), for example DRUNK_DR (2020 only), ALC_DET and DRUG_DET (2020–2021), DEVMOTOR and DEVTYPE (2022 on). None of them is in scope, so the loader can select columns by name without year-specific logic. Inside the in-scope columns, the "not reported" codes are the ones that drift: RUR_URB 8 appears only in 2023–2024 and 9 only in 2024, FUNC_SYS 98 in 2022 and 2024, WEATHER 99 from 2022, LGT_COND 8 in 2020 and 2024 (`07_code_drift.csv`). The remaining drift is sparse categories: 25 of 37 BODY_TYP codes and 35 of 48 PEDCTYPE codes each cover fewer than 1% of deaths, so they appear and disappear from year to year.

### 2.6 Census county file

3,195 rows and 99 columns for all U.S. counties; 67 Florida county rows (SUMLEV 050) plus one state summary row (SUMLEV 040, COUNTY = 0) that must be excluded. Columns POPESTIMATE2020 through POPESTIMATE2025 are present. Florida county totals run from 21,591,325 (2020) to 23,265,838 (2024). Every FARS county code used in Florida matches a Census county code, and every Census county has at least one FARS crash in the period (`09_census_profile.csv`).

---

## 3. The five most consequential quality issues

Ranked by how much they can change the answer to the project question.

1. **Coded unknowns that are not random.** Unknown body type is a property of hit-and-run crashes (57.4% vs 0.16%); unknown speed limit is seven times more common after a hit-and-run; 28.3% of deaths have no usable PBCAT crash type; the alcohol field is unknown for 38.5% of deaths and getting worse. Any rule that drops these rows or imputes them silently changes which patterns come out on top.
2. **The 2024 file is provisional and already looks different.** It is the Annual Report File: 668 deaths against 774 in 2023 (−13.7%), and 31 deaths (4.6%) with RUR_URB not reported, ten times the rate of any final year. 2024 is also the temporal hold-out year in the proposal, so its quality decides whether the hold-out test means anything.
3. **Identity across years and multi-victim crashes.** 96.3% of case numbers recur across the five years, and 42 crashes killed more than one pedestrian. A naive "drop duplicates" on either the case number or the scene attributes would delete real deaths; a naive append of the revised 2024 file would double them.
4. **Sparse and drifting code lists.** Roughly two thirds of the BODY_TYP and PEDCTYPE codes each cover under 1% of deaths, and the "not reported" codes appear in different years. Without a year-aware mapping to a small set of groups, item support fragments, rules fail the four-of-five-years stability test for the wrong reason, and the 2024 unknown codes become invisible.
5. **Geography: the only derived link.** Coordinates are nearly complete (99.9%), so the risk is not missing points but wrong joins: three filler pairs, two repeated points, 2019 block-group boundaries applied to 2020–2024 crashes, and the EPA sentinel −99999 that would enter a numeric column as a real distance. Objective 1 requires walkability on at least 90% of geocoded records, and block-group county digits give a built-in check.

Not on the list, and why: the scope filter (urban, non-freeway) is a design decision of the proposal rather than a data defect; its coverage (81.7%) and the 47 deaths that cannot be classified are treated in section 5. Coordinates, junction relation, hour, and county are complete or nearly so and need only the checks already in the schema.

---

## 4. Rules for each issue

Each rule has four parts: a detection rule that a script can run, the planned action, the rationale tied to the question and the textbook, and a verification test that runs after the transformation. Tests will live in `tests/verify_cleaning_rules.sql` (database side) and `pipeline/profile_raw.py` (raw side). The number that a test must reproduce is quoted so that a wrong load cannot pass silently.

### Issue 1: coded unknowns that are not random

**Detection rule.** For every coded column, membership in the documented unknown set: VSPD_LIM ∈ {98, 99}; BODY_TYP ∈ {98, 99}; LGT_COND ∈ {6, 7, 8, 9}; FUNC_SYS ∈ {96, 98, 99}; RUR_URB ∈ {6, 8, 9}; RELJCT2 ∈ {98, 99}; PEDLOC, PEDPOS, PBCWALK, PBSWALK = 9; PEDCGP ∈ {600, 990}; AGE ∈ {998, 999}; SEX, DRINKING ∈ {8, 9}. The sets come from the FARS Analytical User's Manual and are stored once, in `code_lookup`, not in the scripts. The detection is measured per year and cross-tabulated against HIT_RUN and year (`08b_missingness_structure_consistency.csv`).

**Planned action.** Take the third of the textbook's three options, *ignore the missing value during analysis*, never the first (eliminate the object) and, with one narrow exception, never the second (estimate). Concretely: (a) the code stays in the database column exactly as FARS wrote it (every coded column is NOT NULL; only true absences such as coordinates become NULL); (b) in the transaction view each unknown becomes an explicit item such as `speed=unknown` so that the row still counts in every support denominator; (c) items whose value is "unknown" are excluded from rule *antecedents* in the mining step, so no rule can read "if speed is unknown then …"; (d) LGT_COND 6 is mapped to the item `light=dark, lighting unknown`, kept separate from `dark, not lighted` and `dark, lighted`, because the dark part is known and is what the question asks about; (e) for PEDCGP, the crossing-location items come from PEDLOC, PEDPOS and PBCWALK, which are complete, and the PBCAT group is a secondary item with `crash_group=circumstances unknown` covering codes 600 and 990; (f) DRINKING is used only as a three-level stratifier (yes / no / unknown), and the proposal's sensitivity check ("do the top patterns hold without alcohol-involved deaths?") is reported next to the unknown share, never as a clean split. The exception: none of the unknowns is estimated from other rows. The multi-vehicle case (400 deaths, 17 with disagreeing speed limits) keeps the striking vehicle's own value.

**Rationale.** The question is about roadway conditions. The variables that are missing most (body type, speed) are missing *because* of a crash characteristic (the driver fled) that itself correlates with darkness and arterials. Dropping those 697 deaths would remove 18.7% of the population and specifically the deaths that occur in the conditions the question is after. Imputing speed from the road class would build the antecedent into the consequent. Keeping "unknown" as a visible item follows the proposal's promise that "speed limit unknown" is itself something a planner should see.

**Verification test.** After the load and the view build: (1) for each variable, `count(item = unknown)` in `v_ped_transactions` equals the count of unknown codes in the raw files for the same year (2020–2024 values in `04_variable_profile.csv`; for VSPD_LIM 31, 49, 44, 48, 36); (2) `count(*)` of the view equals 3,053 with the current files, and no row has been removed because of an unknown code; (3) zero NULLs in the coded columns of `crash`, `vehicle`, `pedestrian`, `ped_crash_type`; (4) no mined rule has an "unknown" item on its left-hand side; (5) the cross-tab "BODY_TYP unknown by HIT_RUN" recomputed from the database reproduces 400 / 697 and 5 / 3,039.

### Issue 2: the provisional 2024 Annual Report File

**Detection rule.** The release label is recorded per file in `source_file.release` ('Final' for 2020–2023, 'Annual Report File' for 2024), taken from NHTSA's release notes at download time, not inferred from the data. Two data-side detectors run every load and are logged, not used to drop anything: the yearly count of the unit against the previous year (2024: 668 vs 774, −13.7%), and the rate of RUR_URB ∈ {6, 8, 9} per year (2024: 4.6%; 2020–2023: 0.1%–1.4%). A third detector, the month distribution of 2024 against the four final years, shows no year-end gap (December 9.6% vs 9.9%), which argues against incomplete reporting of late-year cases and for a real change plus a coding lag in the roadway variables.

**Planned action.** Load 2024 like any other year, but (a) tag its rows through `source_file` and `etl_run` so that every downstream table can be filtered by release; (b) treat the four-of-five-years stability test as four final years plus a provisional fifth, reporting rules that hold in 2020–2023 and stating separately whether they hold in 2024; (c) keep the 2024 temporal hold-out in the plan but label its result provisional in every deliverable; (d) when NHTSA publishes the 2024 Final file, re-run the pipeline; the load is *by year* (delete the year's rows inside the run's transaction, then insert), so the Final file replaces the ARF rows instead of joining them; (e) write the ARF-versus-Final differences (row counts, changed codes per variable) to `etl_log` and to `docs/evidence/`.

**Rationale.** This is the textbook's *timeliness* issue (2.2.2): a snapshot taken before the source has finished changing. The 31 deaths with unknown RUR_URB cannot be assigned to the urban population, so in 2024 the analysis population is 522 of 668 (78.1%) against 80.7%–84.6% in the final years. If the pattern support is computed per year, 2024 is biased against any pattern whose deaths happen to be the late-coded ones. Naming the file provisional and isolating it in the tests keeps the question answerable now without pretending 2024 is settled.

**Verification test.** (1) `source_file` has exactly five FARS rows per run, and the 2024 row has `release = 'Annual Report File'` until the Final file is loaded; (2) after any reload, `count(pedestrian)` per year equals the raw count for that year's file in the same run (no doubling: a reload of 2024 leaves 2020–2023 counts at 695, 819, 780, 774); (3) `v_dq` reports the RUR_URB-unknown rate by year, and the 2024 value is quoted in the report; (4) the stability table in Week 9 has separate columns for 2020–2023 and 2024.

### Issue 3: identity across years and multi-victim crashes

**Detection rule.** Within one year: uniqueness of ST_CASE in accident, (ST_CASE, VEH_NO) in vehicle, (ST_CASE, VEH_NO, PER_NO) in person and pbtype; count of exact duplicate rows; count of orphan rows. Across years: the number of case numbers that occur in more than one year (3,503 of 3,639). Multiplicity: the number of pedestrian fatalities per crash (42 crashes with two or more; maximum four) and the reconciliation of accident.FATALS and accident.PEDS against person rows (equal in all 3,690 crashes).

**Planned action.** No deduplication of any kind. The primary keys are composite, (year, st_case), (year, st_case, veh_no), (year, st_case, veh_no, per_no), as already built in `sql/01_schema.sql`, so a 2021 and a 2023 case with the same number cannot collide and cannot be merged. Multi-victim crashes produce one transaction per death by design; the crash attributes are repeated, not duplicated. Loads are idempotent per year (issue 2). The reconciliation counts are loaded as `crash.fatals` and `crash.peds` and checked, not trusted.

**Rationale.** Tan et al. (2.2.1) warn that "deduplication" must decide whether two objects that look alike are really one; here the profile shows they are not. The unit is the death. Dropping the second death in a crash would undercount exactly the crashes with the most severe outcomes and would bias county rates in the counties where multi-victim crashes happen. Because the raw files contain zero duplicates and zero orphans, any duplicate that appears later is a pipeline error, and the tests treat it as one.

**Verification test.** (1) `count(pedestrian)` = 3,736 and `count(crash)` = 3,690 with the current files, and by year 695 / 819 / 780 / 774 / 668; (2) `sum(fatals) over crashes` ≥ `count(pedestrian)` and, per crash, the number of pedestrian rows never exceeds `fatals` (measured: equal in every crash); (3) the deferred triggers of `sql/02_cardinality_triggers.sql` accept every crash (at least one pedestrian and one in-transport vehicle: measured true for all 3,690); (4) a deliberate second load of the same year in a new run leaves all counts unchanged; (5) the number of crashes with two or more pedestrian rows equals 42.

### Issue 4: sparse and drifting code lists

**Detection rule.** Per variable and year, the set of observed codes compared with `code_lookup` (which carries `year_from` and `year_to`): any observed code with no label valid for that year fails. Sparsity is measured as the number of codes with support below 1% of deaths (BODY_TYP 25 of 37; PEDCTYPE 35 of 48; PEDCGP 9 of 16). Column drift is measured as columns present in some years only (19, none in scope).

**Planned action.** Discretize and aggregate before mining, once, in the view, with the mapping stored in a table so that it is data, not code: (a) BODY_TYP → six vehicle classes (car; pickup; SUV; van; heavy truck or bus; other or unknown), following the NCSA body-type groupings; (b) PEDCGP → the PBCAT groups already seeded in `pbcat_group`, with 600 and 990 merged into `circumstances unknown` (issue 1) and the six groups below 20 deaths (310, 340, 460, 500, 720, 800) merged into `other`; (c) VSPD_LIM → five ordered bins (≤30, 35–40, 45–50, ≥55, unknown), HOUR → five bins (00–05, 06–11, 12–17, 18–20, 21–23), AGE → five bins plus unknown, exactly as the profile already reports them; (d) every "not reported" and "unknown" code of a variable maps to that variable's single `unknown` item, so RUR_URB 8 and 9 (new in 2023–2024) and RUR_URB 6 land in one place; (e) any observed code with no mapping stops the load, it is not sent to `other`.

**Rationale.** Association rules need items with enough support to be counted, and the stability criterion compares support across years. A code that covers 0.3% of deaths in 2021 and 0% in 2022 fails stability because it is rare, not because the pattern changed. Binarization and discretization (Tan et al., 2.3.6) and aggregation (2.3.1) are the textbook's tools for exactly this, and the book's warning applies: bins must be chosen before looking at the rules, which is why they are fixed here, in Week 6.

**Verification test.** (1) `tests/check_code_domains.py` extended: zero observed (variable, code, year) triples without a valid label; (2) every mapping table is total: `count(distinct raw code)` in the loaded tables equals the count of mapped codes, and no row of the view has a NULL item; (3) for each grouped variable, the sum of group supports equals the sum of raw code supports (3,736 for person-level, 3,690 for vehicle-level variables); (4) no item in the mining input has support below 1% except items that are reported as excluded in the report; (5) the bins used in `v_ped_transactions` are the bins printed in `docs/profile/06_category_frequencies.csv`, checked by a query that recomputes the pooled frequencies from the database and compares them with the CSV.

### Issue 5: geography, the only derived link

**Detection rule.** Coordinates: LATITUDE ∈ {77.7777, 88.8888, 99.9999} or LONGITUD ∈ {777.7777, 888.8888, 999.9999} (3 crashes); a point outside the Florida box 24.3–31.1 N, −87.7 to −79.8 W (0 crashes); identical points shared by different crashes (2 crashes in 2020). County: COUNTY not in the 67 Census codes (0). Block groups, once the EPA file is loaded: GEOID10 not matching `^12[0-9]{10}$`; a joined block group whose county digits (characters 3–5) differ from the crash's COUNTY; NatWalkInd outside 1–20; D4A equal to −99999 (EPA's sentinel for "no transit within range").

**Planned action.** (a) The three filler pairs become NULL in `latitude` and `longitud`, and the death keeps its county; (b) a point-in-polygon join in geopandas assigns `geoid10`, and a point whose block-group county disagrees with the FARS county is *not* joined (geoid10 NULL, logged), because either the coordinates or the county code is wrong and the plan cannot tell which; (c) the two repeated points are kept (two crashes at one location are plausible) and listed in the log; (d) D4A −99999 becomes NULL, never a distance; (e) walkability enters the transactions as an ordinal item with four EPA classes (least, below average, above average, most walkable) plus `unknown` for deaths without a block group; (f) the boundary vintage (2019) and the join date are written to `etl_log` for every run.

**Rationale.** The question's second half, which counties concentrate deaths under each pattern, depends on the county code, which is complete and consistent with the Census list, so county rates are safe. The walkability item is an enrichment, and Objective 1 accepts up to 10% missing walkability; the risk is not missingness but a silently wrong join that would attach the wrong neighbourhood to a death. The county-digit check is a free consistency test, in the sense of Tan et al. 2.2.1, because the same fact (county) is recorded twice, once by the police and once by the spatial join. The sentinel −99999 is a classic artifact that would otherwise pass every range check on a distance.

**Verification test.** (1) `crash.latitude IS NULL` for exactly 3 crashes with the current files, and `(latitude IS NULL) = (longitud IS NULL)` always (schema CHECK); (2) 0 crash points outside the Florida box (schema CHECK); (3) after the join, for every crash with `geoid10`, `substring(geoid10, 3, 3)::int = county`; (4) the share of crashes with a block group is at least 90% and is reported by year; (5) `block_group.d4a` has no negative value (schema CHECK) and the count of NULL `d4a` equals the count of −99999 in the EPA extract; (6) county rates computed from `v_county_rate` sum to 3,736 deaths over the 67 counties, with 3 counties at zero.

---

## 5. How the rules could affect representation and bias

**Population coverage.** The proposal's population is urban, non-freeway Florida. That filter keeps 3,053 of 3,736 deaths (81.7%). It removes 364 rural deaths (9.7%), 272 deaths on interstates and freeways (7.3%), and 47 deaths (1.3%) whose urban or rural status was not coded, two thirds of them in 2024. The patterns will therefore describe the urban street network and say nothing about the rural counties where 33 of 67 counties recorded fewer than 20 deaths in five years. County rates, on the other hand, use all 3,736 deaths, so a rural county's rate can be high while it contributes no pattern. The report will show both numbers side by side rather than let the pattern map imply that rural counties have no problem.

**Who is missing from the antecedents.** Because unknown items never appear on the left-hand side of a rule, the 697 hit-and-run deaths contribute fully to lighting, road-class, time and crossing items but only partly to speed (18.5% unknown) and mostly not to vehicle class (57.4% unknown). Any pattern about vehicle type will under-represent hit-and-run crashes, which are themselves concentrated at night. The report will state the hit-and-run share next to every vehicle-type pattern.

**Alcohol.** DRINKING is unknown for 38.5% of deaths and the unknown share is growing. A sensitivity check that drops "alcohol-involved" deaths would compare 518 known-yes deaths with 1,779 known-no deaths and ignore 1,439, and police reporting of alcohol is unlikely to be random with respect to age, sex, time and place. The plan keeps the three-level stratifier, reports the unknown share, and makes no claim about impairment.

**Multi-victim crashes and county rates.** Keeping every death (issue 3) is the choice that respects the unit; it also means one crash can move a small county's five-year count by several deaths. Counties with fewer than 20 deaths carry the unstable-rate flag from the proposal.

**The provisional year.** With 2024 lower by 13.7% and its roadway codes less complete, any five-year trend or any hold-out result is biased toward "fewer deaths, fewer urban deaths" until the Final file replaces it. Every table that uses 2024 will say so.

**Sensitive fields.** RACE and HISPANIC are not loaded, as the proposal decided. Age, sex, month, hour and coordinates are quasi-identifiers; they stay in the local database, and only aggregates leave it. The profile tables in `docs/profile/` contain counts only; no row in the repository describes an individual death.

**What the rules do not change.** No rule changes a recorded value, estimates a missing one, or removes a death. The only values that become NULL are the three coordinate filler pairs and the EPA sentinel, and both are documented codes for "no value". This is deliberate: the association analysis can absorb an `unknown` item, whereas a silent imputation would be indistinguishable from evidence.

---

## 6. Preserving raw data and logging transformations

**Raw files are immutable and outside Git.** The six downloaded files sit in `data/raw/`, which `.gitignore` excludes, with file permissions set to read-only. `docs/profile/00_manifest_sha256.csv` records name, URL, size, and SHA-256 for each; the pipeline recomputes the hash before every run and refuses to start if a hash has changed. A re-download (for example the 2024 Final file) is a new file with a new hash and a new `source_file` row, never an overwrite of the old one; the old zip is kept until the project ends, then deleted as the proposal's retention rule says.

**Nothing is extracted by hand.** `profile_raw.py` and the Week 7 loader read the CSV members directly from the zips, so there is no intermediate copy that could be edited. Interim parquet files, if any, go to `data/interim/` (also ignored) and are rebuilt from the zips.

**Every run is a record.** The schema already has the four bookkeeping tables from the proposal, and the loader will use them in this order: one `etl_run` row per execution (start, finish, git commit, status); one `source_file` row per input file (source, year, release Final/ARF, URL, SHA-256, retrieval date); one `etl_log` row per step with `rows_in`, `rows_out` and a message, so that every filter and every join says how many rows went in and came out (for example "person → pedestrian: 41,133 in, 3,736 out"); one `validation_result` row per check with pass/fail and a detail string. A failed check sets the run to `failed` and rolls back the load; nothing partial is committed.

**Human-readable evidence in the repository.** Each run also writes text logs to `docs/evidence/` (this week: `06_profile_run.log`), and the profile tables to `docs/profile/`, so a reader can see the numbers without a database. Git tags mark each milestone (`week6-cleaning-plan`, then `db-v0.1` after the first load), so the exact code that produced a number can be checked out.

**Transformations are declared, not hidden.** The mappings of issue 4 (codes to groups, bins) live in tables loaded from CSV files in `sql/`, and the unknown sets of issue 1 live in `code_lookup`. Changing a bin is a data change in a versioned file, visible in `git diff`, not an edit inside a function.

**Reproducing this document.** `python pipeline/profile_raw.py` regenerates every table cited here from the raw zips in about thirty seconds; `tests/verify_cleaning_rules.sql` runs the post-load tests of section 4; against the Week 5 synthetic fixture it executes end to end (`docs/evidence/07_verify_cleaning_rules_on_fixture.log`: the 13 structural tests pass, the 13 count tests fail by design because the fixture holds 16 synthetic deaths, not 3,736).

---

## Sources and AI assistance

- Tan, P.-N., Steinbach, M., Karpatne, A., & Kumar, V. (2019). *Introduction to data mining* (2nd ed.). Pearson. Sections 2.1 (types of data), 2.2 (data quality: measurement and data collection issues, missing values, inconsistent values, duplicate data, timeliness), 2.3 (aggregation, discretization and binarization, variable transformation), Chapter 5 (association analysis).
- National Highway Traffic Safety Administration. (2026). *Fatality Analysis Reporting System (FARS): National CSV files 2020–2024*. https://static.nhtsa.gov/nhtsa/downloads/FARS/ (2024 = Annual Report File).
- National Highway Traffic Safety Administration. (2026). *FARS analytical user's manual, 1975–2024* and *FARS/CRSS pedestrian bicyclist crash typing manual* (DOT HS 813 694). https://static.nhtsa.gov/nhtsa/downloads/FARS/Links%20for%20FARS%20Manuals.pdf
- U.S. Census Bureau. (2026). *County population totals: 2020–2025, Vintage 2025* (CO-EST2025-ALLDATA). https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html
- U.S. Environmental Protection Agency. (2021). *National Walkability Index: Methodology and user guide*; *Smart Location Database v3.0 technical documentation*. https://www.epa.gov/smartgrowth/smart-location-mapping

I used Claude (Anthropic), an AI assistant, to help write the profiling script, tabulate its output, and draft the wording of this plan. The raw files were downloaded by me; the script ran on those files in the assistant's Linux environment, and every number above comes from its output in `docs/profile/`. The question, scope, and design decisions come from my approved proposal and my Week 4–5 work. I reviewed the generated material and I am responsible for the content.
