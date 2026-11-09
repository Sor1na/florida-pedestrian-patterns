# dashboard/ — the Week 12 specification, machine-readable

The design of the dashboard is written in [`docs/Week12_Dashboard_Design_Shkirpan.md`](../docs/Week12_Dashboard_Design_Shkirpan.md). The files here are its machine-readable counterpart, so that the build in Week 13 can be checked against the design instead of against memory, and so that CI fails when the two drift apart:

```
python tests/check_dashboard_spec.py                        # 272 checks, standard library only, no database
python tests/check_dashboard_spec.py --write-countermeasures  # regenerate countermeasures.csv from the rules below
```

| File | One row is… | Used for |
|---|---|---|
| `views.csv` | one view of the dashboard (C1–C3 context, F1–F4 finding, A1–A2 action) with its stage, display order, core/cut-first status, audience tasks, title, question, comparison type, chart form, source fields, comparison, annotation text, the uncertainty element drawn beside it, the limitation blocks placed beside it, the controls that scope it, and its alternative text | design §2–3, §6.5; completion criteria 1–5 |
| `limitations.csv` | one limitation block (L1–L9): the text as it goes on the page (at most 40 words) and the views it sits beside | design §5.5; completion criterion 4 |
| `palette.csv` | one color pair: foreground, background, the WCAG 2 contrast it must reach (4.5:1 text, 3:1 marks, 2:1 the light end of an ordinal ramp), the ratio the design quotes, and, where the pair does not reach it on its own, the mitigation the design gives it | design §6.2; completion criterion 5 |
| `palette_roles.csv` | one color role (series, context gray, map ramp step, heat-table ramp step, ink, surface) with its hex; the script checks the series colors' OKLCH lightness and chroma, their separation under simulated protanopia and deuteranopia (Machado, Oliveira & Fernandes, 2009) and under normal vision, and that each ramp is one hue, monotone in lightness, with a light end that clears the surface | design §6.1; completion criterion 5 |
| `countermeasures.csv` | one roadway pattern of either pre-registered list (the 18 of the primary top-20 that contain a road-class, speed or crossing item, plus the 2 that appear only on the roadway top-20; 20 rows) with its rank on each list, against the eight FHWA proven-countermeasure families of view A2; 1 = the family addresses one of the pattern's conditions | design §3.2 A2 |

**Source-field syntax in `views.csv`.** `v_county_rate.deaths_all` is a column of a view in `sql/04_views.sql`; `crash.rur_urb` a column of a table in `sql/01_schema.sql`; `patterns_topk.csv:obs_support` a column of a CSV under `docs/evidence/week11/`, `docs/profile/` or `dashboard/`; `results_summary.json:results.top_20.mae_pp_candidate` a key path in the Week 11 summary. The check script resolves every reference, so a view cannot name a field that does not exist. No field is person-level: the dashboard role reads aggregates only (`sql/05_roles.sql`, constraint tests E1–E6).

## The eight mapping rules behind `countermeasures.csv`

The matrix is a draft for the Week 13 planner walk-through, not a finding of the mining: it says which proven-countermeasure families are *designed for* the conditions in a pattern, and nothing about what any of them would change here (design §3.2 A2, limitation blocks L1 and L2). The rules are applied by `families_for()` in `tests/check_dashboard_spec.py`; a change to the rules changes the code and the matrix together.

| Family (FHWA proven safety countermeasure) | Marked when the pattern contains… |
|---|---|
| Lighting | `light = dark, not lighted` |
| Crosswalk Visibility Enhancements | any crossing-location item (at intersection, intersection-related, not at intersection), or `road_class = local road`, or `speed_bin = 30 mph or less` |
| Pedestrian Hybrid Beacons / Rectangular Rapid Flashing Beacons | `crossing_location = not at intersection`; or an arterial (principal or minor) or a 35–50 mph speed item with no crossing-location item (uncontrolled crossings likely) |
| Medians and Pedestrian Refuge Islands | an arterial or a 45 mph-or-more speed item, and no intersection item |
| Road Diets (roadway reconfiguration) | an arterial with a 35–40 or 45–50 mph speed item |
| Appropriate Speed Limits for All Road Users / Speed Safety Cameras | `speed_bin` of 45–50 mph or 55 mph or more |
| Leading Pedestrian Interval | `crossing_location` at intersection or intersection-related |
| Walkways | `road_class` local road or collector, or `speed_bin = 30 mph or less` |

Time-of-day items map to no family (they inform when enforcement runs, not what is built), and "dark, lighted" does not mark Lighting, since lighting is present; the engineer's site review decides whether its level or uniformity is adequate.

Source for the families: Federal Highway Administration, *Proven Safety Countermeasures*, https://highways.dot.gov/safety/proven-safety-countermeasures.
