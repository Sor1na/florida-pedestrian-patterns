# Week 11: Final Evaluation, Error Analysis, and Bounded Claims

**Built for Cars, Deadly for Walkers: mining the roadway conditions behind Florida's pedestrian deaths, 2020–2024**

Yelysei Shkirpan · Capstone Project, B.S. Data Science · Eastern Florida State College · November 1, 2026

Repository: https://github.com/Sor1na/florida-pedestrian-patterns

**What this document is.** The one read of the held-out year, 2024, by the experiment that Week 10 pre-registered ([`Week10_Experiment_Design_Shkirpan.pdf`](Week10_Experiment_Design_Shkirpan.pdf), [`analysis/experiment_config.json`](../analysis/experiment_config.json)), and what that read does and does not support. Every number below is in [`docs/evidence/week11/`](evidence/week11), written by `python analysis/experiment.py test` in one run; the pattern list and the metric definitions were fixed before that run. Numbers are shares of in-scope deaths (urban, non-freeway) in percentage points (pp) unless said otherwise; brackets are 95% intervals.

| Required item | Where |
|---|---|
| 1. Final evaluation design and untouched test evidence | section 1 |
| 2. Primary and secondary metrics with consequence-based rationale | section 2 |
| 3. Baseline and candidate results | section 3 |
| 4. Error analysis with representative failure cases | section 4 |
| 5. Performance across a subgroup and a period | section 5 |
| 6. One supported claim, one unsupported claim, the principal limitation | section 6 |
| Completion criteria | section 7 |

---

## 1. Final evaluation design, and the evidence that the test year was untouched

**Design, as pre-registered.** Patterns = closed frequent itemsets of 2–4 items over road class, speed limit, lighting, crossing location and time of day, mined with FP-Growth on 2020–2023 (2,531 in-scope deaths) at the locked thresholds (minimum support 3%, minimum lift 1.5), ranked by lift, top K = 20. Each pattern's **predicted** 2024 share is its 2020–2023 share (candidate) or the product of its items' 2020–2023 shares (baseline: statistical independence). The **observed** share is measured once, on the 522 in-scope deaths of the 2024 Annual Report File (516 crashes). Intervals come from a cluster bootstrap of 2024 crashes (B = 1,000, seed 20262024); the permutation null from 500 column-wise shuffles of the fit rows (seed 20262025).

**Evidence that 2024 was not used for anything but this read.**

| Control | Evidence |
|---|---|
| Tuning never read 2024 | `evidence/week10/tune_run.log`: "read 2531 rows from the database with year <= 2023; max year read 2023"; the SQL filter and an assertion in `stage_tune` |
| Parameters locked before the test, by a committed file | `analysis/locked_params.json`: min_support 0.03, min_lift 1.5, K 20, max_len 4, written at commit `528311f` with a clean tree (`git_dirty: false`); committed as `14bf0ca` |
| The code was frozen before the test | `evidence/week11/test_run.log` header: "git commit 14bf0ca…; dirty=False"; config SHA-256 `26ecf204…` equal to the one in the locked file; transactions SHA-256 `1894047c…` equal to the one in the locked file |
| The test stage ran exactly once | `evidence/week11/test_runs.log` has one `started` and one `completed` line (01:07:11 to 01:07:55, 2026-11-01); the stage refuses a second run without `--force "<reason>"`, which would itself be logged there |
| The pattern list was not edited after seeing 2024 | `patterns_topk.csv` is produced by the same run as the metrics; the roadway secondary list was defined in Week 10 §5.2 item 8, before the run |
| The hold-out is the provisional file | `source_file.release = 'Annual Report File'` for 2024; the summary carries `test_year_release: "Annual Report File (provisional)"` |

One amendment was made between tuning and the test, in writing and before 2024 was read (Week 10 §5.2, items 7–8): a flag for patterns that are true by construction (daylight with midday, daylight with morning) and a secondary "roadway" list restricted to patterns that contain a road-class, speed or crossing item. The primary metric is unchanged and is reported on the unfiltered list.

## 2. Metrics and why they fit the decision

The decision this evidence serves is a planner's ranking of condition combinations to act on, where each combination is described by its share of deaths. The consequence of a wrong share is money aimed at fewer deaths than claimed (over-prediction) or a real target left unfunded (under-prediction); both are measured in percentage points of deaths and are roughly symmetric, which is why the primary metric is an absolute error in those units rather than confidence, lift or a count of significant rules, none of which says how the claim fares the next year.

| Metric | Definition | Consequence it guards |
|---|---|---|
| **MAE_pp (primary)** | mean over the top-K patterns of \|predicted − observed 2024 share\|, in pp; candidate and baseline on the same K patterns | the size of the error in the number a planner would quote |
| replication rate | share of top-K with 2024 share ≥ 3% and 2024 lift > 1 | whether a listed pattern is still a pattern at all |
| signed bias | mean (predicted − observed) | a systematic over- or under-statement |
| rank agreement (Spearman) | between 2020–2023 lift and 2024 lift over the top-K | whether "fund first" order survives |
| coverage | share of 2024 deaths carrying at least one top-K pattern | how much of the problem the list addresses |
| permutation null | pattern count, maximum lift and replication rate under column-wise shuffles that keep every marginal | whether the miner is reporting chance |

## 3. Results: baseline against candidate

### 3.1 Primary result (unfiltered top-20, K = 20)

| | Candidate (FP-Growth patterns, 2020–2023 share) | Baseline (independence) | Difference |
|---|---|---|---|
| **MAE_pp** | **0.82 [0.66, 1.52]** | **2.57 [2.04, 3.24]** | **−1.75 [−2.36, −0.63]** |
| signed bias, pp | +0.37 | −2.57 | |
| replication rate | 17 of 20 = 0.85 [0.60, 0.90] | (not defined: the baseline predicts lift 1) | |
| rank agreement | ρ = 0.92 | | |
| coverage of 2024 deaths | 45.4% [41.4%, 49.5%] (237 of 522) | | |

Reading: the twenty combinations named from 2020–2023 described 2024 to within about 0.8 pp each on average, three times closer than the assumption that the five conditions are unrelated; the interval of the difference excludes zero. The candidate overstates shares slightly (+0.37 pp on average, as 2024 is a smaller and differently coded year, section 4.3), the baseline understates every one of them by construction. Seventeen of twenty patterns were still present at or above the support floor with lift above one; the order by lift survived almost intact.

Secondary cuts (same run):

| List | MAE_pp candidate | MAE_pp baseline | difference | replication | coverage | ρ |
|---|---|---|---|---|---|---|
| top-10 | 0.80 [0.56, 1.53] | 3.02 [2.29, 3.88] | −2.22 [−3.12, −0.86] | 9/10 | 21.3% | 0.87 |
| roadway top-20 (secondary; no light-and-time-only patterns) | 0.84 [0.67, 1.51] | 2.22 [1.74, 2.87] | −1.38 [−1.98, −0.37] | 16/20 = 0.80 [0.55, 0.90] | 46.4% | 0.91 |
| roadway top-10 | 0.79 [0.52, 1.60] | 2.70 [1.93, 3.55] | −1.91 [−2.80, −0.44] | 9/10 | 20.3% | 0.87 |

**On the bootstrap intervals:** the lower bound of a resampled MAE can sit below and the upper bound well above the point estimate, because absolute errors grow when a 522-death year is resampled; the intervals are reported as computed, not centred.

### 3.2 Permutation null: is the candidate finding structure or noise?

| Statistic | Observed | Null (500 shuffles) | p (one-sided) |
|---|---|---|---|
| patterns passing 3% support and lift 1.5 | 28 | mean 0.002, 95th percentile 0 | 0.002 (0 of 500 ≥ observed) |
| maximum lift | 5.89 | mean 1.52, 95th percentile 1.52 | 0.002 |
| replication rate of the real top-20 on a shuffled 2024 | 0.85 | mean 0.10, 95th percentile 0.20 | 0.002 |

With the marginals kept and the joint structure destroyed, the miner finds essentially nothing at these thresholds. The 28 patterns are not an artefact of skewed marginals (Tan et al., §5.8) or of the number of comparisons.

### 3.3 The twenty patterns

`evidence/week11/patterns_topk.csv`; shares in % of in-scope deaths. "Construction" marks the two patterns true because of the sun.

| # | Pattern (items) | 2020–23 share | lift | 2024 share [Wilson 95%] | 2024 lift | replicated |
|---|---|---|---|---|---|---|
| 1 | daylight · midday (construction) | 7.7 | 5.89 | 7.1 [5.2, 9.6] | 6.14 | yes |
| 2 | daylight · not at intersection · midday | 5.2 | 5.52 | 4.6 [3.1, 6.8] | 5.68 | yes |
| 3 | local road · ≤ 30 mph | 5.5 | 4.82 | 4.6 [3.1, 6.8] | 3.28 | yes |
| 4 | principal arterial · daylight · midday | 3.2 | 4.74 | 2.3 [1.3, 4.0] | 4.28 | **no** (share < 3%) |
| 5 | principal arterial · ≥ 55 mph · dark, not lighted · not at intersection | 4.2 | 4.62 | 3.3 [2.0, 5.2] | 4.22 | yes |
| 6 | local road · ≤ 30 mph · not at intersection | 3.7 | 4.48 | 3.1 [1.9, 4.9] | 3.11 | yes |
| 7 | principal arterial · ≥ 55 mph · dark, not lighted | 4.6 | 3.65 | 3.8 [2.5, 5.8] | 3.48 | yes |
| 8 | ≥ 55 mph · dark, not lighted · not at intersection | 5.0 | 2.84 | 4.4 [3.0, 6.5] | 2.66 | yes |
| 9 | minor arterial · 35–40 mph · dark, lighted · night (20–23) | 3.5 | 2.41 | 3.1 [1.9, 4.9] | 2.13 | yes |
| 10 | ≤ 30 mph · daylight | 5.0 | 2.29 | 6.5 [4.7, 9.0] | 2.78 | yes |
| 11 | daylight · morning (construction) | 3.9 | 2.27 | 5.4 [3.7, 7.6] | 2.87 | yes |
| 12 | ≥ 55 mph · dark, not lighted | 5.4 | 2.23 | 5.0 [3.4, 7.2] | 2.10 | yes |
| 13 | local road · daylight | 3.1 | 2.07 | 3.3 [2.0, 5.2] | 2.05 | yes |
| 14 | principal arterial · 45–50 mph · dark, lighted · night (20–23) | 8.6 | 2.06 | 8.0 [6.0, 10.7] | 2.28 | yes |
| 15 | 45–50 mph · dark, not lighted · not at intersection · late night (0–5) | 3.7 | 1.94 | 2.5 [1.5, 4.2] | 1.25 | **no** |
| 16 | principal arterial · ≥ 55 mph · not at intersection | 6.0 | 1.94 | 4.8 [3.3, 7.0] | 1.78 | yes |
| 17 | dark, lighted · intersection-related · night (20–23) | 3.2 | 1.78 | 2.1 [1.2, 3.7] | 1.27 | **no** |
| 18 | principal arterial · 45–50 mph · dark, lighted · late night (0–5) | 3.8 | 1.72 | 4.6 [3.1, 6.8] | 2.09 | yes |
| 19 | collector · 35–40 mph · not at intersection | 4.3 | 1.67 | 5.0 [3.4, 7.2] | 1.35 | yes |
| 20 | principal arterial · ≥ 55 mph | 7.2 | 1.67 | 6.3 [4.5, 8.7] | 1.65 | yes |

For planners the same patterns read as rules (`patterns_rules.csv`): on the fit years, *≥ 55 mph and dark, not lighted → not at an intersection* holds with confidence 0.92; *≥ 55 mph → principal arterial* with 0.87; *collector and 35–40 mph → not at an intersection* with 0.83. The largest single pattern by share is #14, the lighted 45–50 mph principal arterial at night (8.6% of deaths, 8.0% in 2024).

## 4. Error analysis

### 4.1 The three patterns that did not replicate

| # | Pattern | What happened in 2024 | Diagnosis |
|---|---|---|---|
| 4 | principal arterial · daylight · midday | 2.3% [1.3%, 4.0%], lift 4.28 | **a threshold failure, not a pattern failure**: the lift is intact; the share fell under the 3% floor (12 deaths). The pattern was already below 3% in 2020 and 2022 (`stability_by_year.csv`: 2.6%, 2.5%), so the four-year stability flag was false before the test. It is also a sub-pattern of the daylight-midday construction pair |
| 15 | 45–50 mph · dark, not lighted · not at intersection · late night | 2.5%, lift 1.25; among "no alcohol reported" deaths 0.8%, lift 1.00 | **a real weakening**: both share and lift fell; this is one of the two patterns where the independence baseline predicted 2024 better than the candidate (margin 0.6 pp). Four items at 3.7% support is the sparsest kind of pattern on the list; its 2021 spike (4.6%) carried it into the top 20 |
| 17 | dark, lighted · intersection-related · night | 2.1%, lift 1.27 | **driven by one year**: 5.1% in 2020, then 2.7%, 2.6%, 2.6%; the four-year stability flag was false. The baseline beat the candidate here too (margin 0.8 pp). A pattern that owes its lift to one year should not have been quoted with its pooled share |

Across the list, the stability flag computed on the fit years would have warned about the risk: 14 of the 15 patterns present in all four fit years replicated; 3 of the 5 that were not did.

### 4.2 The largest residuals, in both directions

| Direction | Patterns | Size | Reading |
|---|---|---|---|
| **under-predicted** (2024 share higher) | #10 ≤ 30 mph · daylight (−1.5 pp), #11 daylight · morning (−1.5 pp), #18 principal arterial · 45–50 · dark, lighted · late night (−0.8 pp), #19 collector · 35–40 · not at intersection (−0.6 pp) | up to 1.5 pp | 2024 has slightly more low-speed daylight deaths and a higher collector share (17.6% vs 12.3% of deaths), which lifts every collector pattern; see 4.3 |
| **over-predicted** (2024 share lower) | #15 (+1.2 pp), #16 principal arterial · ≥ 55 · not at intersection (+1.2 pp), #17 (+1.1 pp), #5 (+1.0 pp), #4 (+0.9 pp), #3 local road · ≤ 30 (+0.9 pp) | up to 1.2 pp | the principal-arterial share of 2024 deaths fell from 52.2% to 46.6%, so every pattern containing it is over-predicted by a little; the high-speed dark patterns (#5, #7, #16, #20) are also the ones that nearly vanish in the five largest counties (section 5.1) |

Hit-and-run deaths are not concentrated in the failures: their share within each pattern's 2024 deaths runs from 0% to 31% (`error_analysis.csv`, column `hit_and_run_share_2024`) with the three failed patterns at 8%, 15% and 18%, close to the 2024 average.

### 4.3 The test year itself as a failure case

The 2024 file is the provisional Annual Report File. Three things in it move every number above and are not under the method's control:

- **It is smaller**: 668 deaths against 774 in 2023; 522 in scope against 625. Every 2024 share rests on about 100 fewer deaths than a Final year would give, so its Wilson intervals are wide (a 3% pattern is 16 deaths).
- **Its roadway coding differs**: 31 of 668 deaths (4.6%) have no urban/rural code and fall out of the analysis population (0.1%–1.4% in Final years, Week 6 issue 2); among those that stay, principal arterials fall from 52.2% to 46.6% of deaths and collectors rise from 12.3% to 17.6%. Whether that is a real shift or a coding lag that the Final file will revise cannot be known from this file. `unknown_share_by_year.csv` shows the item-level unknowns themselves barely moved (speed unknown 6.2% → 6.3%; lighting unknown 0.3% → 0.8%).
- **The single test year gives one draw.** All intervals here are over deaths within 2024, not over years; a second hold-out year would be needed to say how much patterns move from year to year beyond sampling noise. The per-year table in section 5.2 is the closest available substitute.

When NHTSA publishes the 2024 Final file, the pipeline reloads it (Week 7 §6.5) and `test` is run again with `--force "2024 Final file"`, which `test_runs.log` records; both results will be reported side by side.

## 5. Subgroup and period

### 5.1 Subgroup: the five most populous counties against the other 62

Miami-Dade, Broward, Palm Beach, Hillsborough and Orange hold 46% of Florida's 2020–2024 person-years and 233 of the 522 in-scope 2024 deaths (44.6%). `subgroup_county.csv`:

| Group (2024 deaths) | MAE_pp candidate | MAE_pp baseline | patterns with 2024 lift > 1 |
|---|---|---|---|
| five most populous (233) | 1.94 | 2.23 | 18 of 20 |
| other 62 counties (289) | 1.33 | 3.31 | 20 of 20 |
| roadway list, five most populous | 2.11 | **1.85** | 17 of 20 |
| roadway list, other counties | 1.24 | 3.09 | 20 of 20 |

The pooled result hides a geographic split. In the five large counties the candidate's advantage over independence almost disappears, and on the roadway list the baseline is closer. The reason is one family of patterns: the **high-speed, dark, unlit arterial** combinations (#5, #7, #16, #20) are predicted at 4–7% of deaths but account for 0.9%, 1.3%, 1.7% and 2.6% of 2024 deaths in the five large counties, against 5.2%, 5.9%, 7.3% and 9.3% in the rest of the state (`subgroup_county.csv`). Deaths on 55 mph roads are 1.6%–4.4% of the large counties' in-scope deaths across the five years and about 8% statewide. Conversely the **lighted 45–50 mph principal arterial at night** (#14) is a large-county pattern: 9.4% of their 2024 deaths against 6.9% elsewhere. The pooled list is right about the state and wrong about where each pattern lives, which is exactly the question the project's Objective 3 (county concentration) exists to answer; Simpson's paradox in the sense of Tan et al. §5.7.3 is not present (no lift reverses sign), but the shares shift enough to change a county's priorities.

**Sensitivity to alcohol involvement** (proposal §10; `sensitivity_alcohol.csv`): restricting 2024 to the 253 deaths with "no alcohol reported" (alcohol is unknown for 44.1% of 2024 deaths, so this is not a clean split), all 20 patterns keep lift above 1 and 17 keep lift ≥ 1.5; the shares shift toward daylight (pattern #1 rises from 7.1% to 11.5%), as expected when night-time alcohol-involved deaths are removed; the candidate's MAE on this subset is 1.88 pp against 3.50 pp for the baseline.

### 5.2 Period: each year on its own

`stability_by_year.csv` gives every pattern's share and lift in 2020, 2021, 2022, 2023 and 2024 separately. Fifteen of the twenty patterns were at or above 3% in all four fit years; their lifts move within narrow bands (for example #5: 4.87, 5.00, 4.53, 4.09, then 4.22 in 2024; #14: 1.91, 1.93, 2.39, 2.03, then 2.28). The five that were not stable (#4, #6, #11, #13, #17) are the small ones (3–4%) and the two daylight constructions; two of the three failures are among them. Year-to-year movement of a 3–5% share is about ±1 pp in these tables, which is the same size as the candidate's test error: the method is, in 2024, about as accurate as one Final year is of the next.

## 6. One supported claim, one unsupported claim, and the principal limitation

**Supported.** *On Florida's urban, non-freeway roads, the condition combinations that most characterised pedestrian deaths in 2020–2023 recurred in 2024 at close to the same shares: twenty combinations predicted their 2024 shares to within 0.8 pp on average (95% interval 0.7–1.5 pp), 1.75 pp closer than assuming the conditions are unrelated (interval 0.6–2.4 pp), seventeen of the twenty stayed above the support floor with lift above one, and none of this is reproduced when the joint structure is shuffled away (p = 0.002). Chief among the recurring, roadway-specific combinations are deaths on principal arterials at 55 mph or more in the dark without lighting, away from intersections (4.2% of deaths in 2020–2023, 3.3% in 2024, lift above 4 in every year), on lighted 45–50 mph principal arterials at night (8.6%, then 8.0%), and on local roads posted at 30 mph or less (5.5%, then 4.6%).* Everything in this claim is a share of deaths in a stated population, measured on a year the method never saw, with its interval.

**Not supported.** *"Dark, unlit high-speed arterials are Florida's most dangerous pedestrian environment, and lighting them would prevent those deaths."* The evidence does not reach this for three separate reasons. There is no exposure denominator: FARS counts deaths, not crossings or pedestrian-miles, so a pattern's share of deaths says where deaths happen, not where the risk per pedestrian is highest; a 55 mph arterial with few pedestrians can have a small share and a huge per-pedestrian risk, or the reverse. The design is descriptive: no counterfactual, no comparison with lit roads of the same class and traffic, so nothing here estimates what lighting would change. And the pattern is geographically uneven: it is 5–9% of deaths outside the five largest counties and about 1–3% inside them, so as a statewide headline it misdescribes the counties where almost half of the deaths occur.

**Principal limitation.** The hold-out is one provisional year. All uncertainty quoted here is sampling uncertainty within 2024's 522 deaths; a single year cannot show how much the patterns move between years for reasons other than sampling, and this particular year is the Annual Report File, 13.7% smaller than 2023, with 4.6% of its deaths uncodable to the analysis population and a roadway-class mix that may still change in the Final release. The result should be read as "the patterns held once, in a year that is still being corrected", and re-read when the Final file is loaded. Two smaller limitations shape the comparison itself and are stated so they are not mistaken for strength: the independence baseline is handicapped by construction (patterns were selected for having lift ≥ 1.5 on the fit years, so if they recur at all the baseline under-predicts them; the informative parts of the comparison are therefore the replication rate, the rank agreement and the permutation null, not the gap alone), and the primary metric favours small-support patterns, whose absolute errors are small in percentage points, which is part of why tuning chose the 3% floor and why the list covers 45% of deaths with twenty patterns of 3–9% each rather than a few large ones.

## 7. Completion criteria

| Criterion | Where it is met |
|---|---|
| Test evidence was not used for tuning | §1: SQL year filter and assertion in `tune`; locked parameters committed before the test (`528311f` → `14bf0ca`); one entry in `test_runs.log`; matching hashes |
| Metrics match the intended decision | §2: the error is in percentage points of deaths, the unit of a planner's claim; replication and rank agreement cover "still a pattern" and "fund first" |
| Results include uncertainty or variability | §3: cluster-bootstrap intervals on every metric, Wilson intervals on every share, a 500-shuffle permutation null; §5.2 year-by-year variability |
| Errors and subgroup performance are examined | §4: three failures diagnosed one by one, residuals in both directions tied to the 2024 file's composition; §5: large-county subgroup (where the method's advantage nearly vanishes), alcohol sensitivity, per-year stability |
| Claims do not exceed the evidence | §6: the supported claim is a share-of-deaths statement with intervals on an untouched year; the unsupported claim names the three missing pieces (exposure, counterfactual, geography); the limitation is the single provisional hold-out |

---

## Sources and AI assistance

- Tan, P.-N., Steinbach, M., Karpatne, A., & Kumar, V. (2019). *Introduction to data mining* (2nd ed.). Pearson. §5.4 (closed itemsets), §5.6 (FP-Growth), §5.7 (evaluation of association patterns, interest factor, Simpson's paradox), §5.8 (skewed support), §3.4–3.6 (validation and holdout), chapter 10 (randomisation tests, multiple comparisons).
- Raschka, S. (2018). MLxtend. *Journal of Open Source Software, 3*(24), 638.
- National Highway Traffic Safety Administration. (2026). *FARS National CSV files 2020–2024* (2024: Annual Report File). https://static.nhtsa.gov/nhtsa/downloads/FARS/
- U.S. Census Bureau. (2026). *County population totals 2020–2025, Vintage 2025*. https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html
- This repository: `analysis/experiment.py`, `analysis/experiment_config.json`, `analysis/locked_params.json`, `docs/evidence/week10/`, `docs/evidence/week11/`, `docs/Week10_Experiment_Design_Shkirpan.md`.

I used Claude (Anthropic), an AI assistant, to help write the experiment code, run the pre-registered stages on the real database, and draft this document from the run's output files. The design, the metric and the pattern list were fixed in Week 10 before the test stage was run; the test stage ran once on my data. I reviewed the generated material and the numbers against the evidence files, and I am responsible for the content.
