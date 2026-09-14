# Sample records

Synthetic rows used to test the conceptual data model (see the main README, section 4). They follow the FARS, PBCAT, EPA, and Census code lists but are not copied from any real case. Population and walkability numbers are placeholders in a realistic range.

One file per entity; the composite keys are the same as in the ER diagram.

| File | Key columns | Notes |
|---|---|---|
| `crash.csv` | `year`, `st_case` | `geoid10`, `latitude`, `longitud` are empty for E2 (coordinates not reported) |
| `vehicle.csv` | `year`, `st_case`, `veh_no` | in-transport vehicles only |
| `pedestrian.csv` | `year`, `st_case`, `veh_no` (0), `per_no` | `str_veh` is the striking vehicle's `veh_no` in the same crash |
| `ped_crash_type.csv` | same four columns as `pedestrian.csv` | one row per pedestrian |
| `county.csv` | `county_fips` | includes Lafayette (67), which has no crash, to test the optional side of COUNTY — CRASH |
| `county_population.csv` | `county_fips`, `year` | one row per county and year, 2020–2024 |
| `block_group.csv` | `geoid10` | only the four block groups referenced by the records are included; the `geom` polygon is omitted from the CSV; `d4a` = -99999 means no transit stop nearby and becomes NULL on load |

## Which rows belong to which record

| Record | `year` | `st_case` | What it tests |
|---|---|---|---|
| R1 | 2021 | 120417 | the archetype: dark, unlit arterial, mid-block; every link present |
| R2 | 2023 | 120417 | intersection, lighted, turning vehicle; same `st_case` as R1, different year |
| R3 | 2022 | 121088 | walking along the road, no sidewalk; an unknown code kept as a value |
| E1 | 2024 | 120078 | one crash, two pedestrian deaths; 2024 Annual Report File |
| E2 | 2022 | 121307 | hit-and-run, coordinates not reported, no block group |

Run `python tests/check_samples.py` from the repository root to check the business rules against these rows.
