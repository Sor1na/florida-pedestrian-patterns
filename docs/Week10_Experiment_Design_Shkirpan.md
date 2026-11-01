# Week 10: A Leakage-Safe, Reproducible Analytical Experiment

**Built for Cars, Deadly for Walkers: mining the roadway conditions behind Florida's pedestrian deaths, 2020–2024**

Yelysei Shkirpan · Capstone Project, B.S. Data Science · Eastern Florida State College · October 2026

Repository: https://github.com/Sor1na/florida-pedestrian-patterns

**What this document is.** The experiment, written down and frozen *before* any pattern was mined on the real data. It says what is being estimated, on which unit, from which features, how the years are split, what the baseline and the candidate method are, what the one primary metric is, and how anyone can rerun the whole thing and get the same numbers. The settings below are also stored machine-readably in [`analysis/experiment_config.json`](../analysis/experiment_config.json), which the code reads; the document and the file were committed together, so a later change to either is visible in the Git history. Results are **not** in this document on purpose: they belong to the Week 11 evaluation, which reads the held-out year exactly once.

| Required item | Where |
|---|---|
| 1. Analytical task and one-sentence estimand | section 1 |
| 2. Unit of analysis, sought structure, decision time, audience | section 2 |
| 3. Feature table: definitions, sources, availability time, exclusions | section 3 |
| 4. Training, validation and test strategy with rationale | section 4 |
| 5. A simple baseline and one candidate method | section 5 |
| 6. Primary metric, reproducibility controls, seeds, software versions | section 6 |
| Methods basis (course text) | section 7 |
| Completion criteria | section 8 |

---

## 1. The analytical task and the estimand

**Task.** Association analysis (frequent-itemset and rule mining) over the in-scope pedestrian deaths, followed by a temporal hold-out test of the patterns found. The task is unsupervised: there is no label to predict. What is sought is *structure*, the combinations of roadway conditions that co-occur in fatal pedestrian crashes more often than chance, and the test asks whether that structure, found in earlier years, is still there in a year the miner never saw.

**Estimand (one sentence).** *Among pedestrian deaths on Florida's urban, non-freeway roads, which combinations of two to four conditions drawn from road class, posted speed limit, lighting, crossing location and time of day occur together more often than statistical independence of those conditions predicts, and how closely does the frequency of each such combination, measured in 2020–2023, match its frequency in the held-out year 2024?*

The second half of the sentence is what makes this an experiment rather than a description. A planner who funds a countermeasure against a pattern is betting that the pattern will still account for a similar share of deaths next year; the experiment measures how good that bet is, and compares it with the simplest competing bet, that the conditions are unrelated.

**What the experiment does not claim.** It does not estimate risk per pedestrian or per crossing (FARS has no exposure denominator), it does not say that any condition *causes* deaths, and it says nothing about rural roads or freeways, which the proposal excludes (Week 6 §5).

## 2. Unit of analysis, sought structure, decision time, audience

| | |
|---|---|
| **Unit of analysis** | One pedestrian fatality in the analysis population: one row of `v_ped_transactions` (urban, `RUR_URB = 2`; not interstate or freeway, `FUNC_SYS ∉ {1, 2}`). 3,053 rows across 2020–2024 (588 / 674 / 644 / 625 / 522 by year; `docs/profile/02_unit_of_observation.csv`, reproduced by the Week 8 real-data load). Each row is one transaction of exactly five items, one per variable in section 3. |
| **Why the death and not the crash** | The project question counts deaths (Week 4 §"Unit of observation", README). A crash that kills two pedestrians is two transactions that share their crash-level items. This is a *group dependency*: 2,510 crashes produced the 2,531 in-scope deaths of 2020–2023 (21 shared scenes, 0.8%). It is handled in two places, the split (years never cut a crash in two, section 4) and the uncertainty estimates (resampling is by crash, not by death, section 6). |
| **Sought structure** | Closed frequent itemsets of length 2–4 over the five item variables, each with its support (share of deaths), its lift against independence, and, for reporting, the association rules that can be read off it (single-item consequent, with confidence). "Closed" means no superset has the same support, so the list carries no redundant sub-patterns (Tan et al., §5.4). |
| **Intended decision and its time** | FDOT's State Safety Office and the Florida MPOs programme pedestrian countermeasures (lighting, crossings, medians, speed management) in an annual cycle, after NHTSA publishes a FARS year. The decision time for this experiment is therefore "the planning cycle after the 2023 Final file", with 2020–2023 as the knowledge available then and 2024 as the year the decision is for. Nothing dated after the crash record enters a feature; nothing from 2024 enters the mining, the tuning or the parameter choice. |
| **Audience** | Safety planners at FDOT and the MPOs, who decide which countermeasures and which counties to fund first (proposal; README). They read patterns as sentences ("dark, not lighted + 45–50 mph + not at an intersection: 18% of deaths") and need to know how far such a share can be trusted for the coming year. |

## 3. Feature table

All items are derived from `v_ped_transactions` ([`sql/04_views.sql`](../sql/04_views.sql)), whose bins were fixed in Week 6 (issue 4, "the bins must be chosen before looking at the rules") and have not changed since. Shares below are measured on the 2020–2023 fit years (2,531 deaths), so this document does not look at 2024.

### 3.1 Item variables (the mining input)

| Variable (item prefix) | Definition and values | Source column(s) | Available when | Share of 2020–2023 deaths per value |
|---|---|---|---|---|
| `road_class` | functional class of the trafficway: principal arterial (FUNC_SYS 3), minor arterial (4), collector (5–6), local road (7), unknown | FARS `accident.FUNC_SYS` | at crash record (coded by the state from the roadway inventory; Final file 12–18 months after year end) | principal arterial 52.2%, minor arterial 26.6%, collector 12.3%, local road 8.9% |
| `speed_bin` | posted speed limit of the *striking* vehicle's trafficway: 30 mph or less, 35–40, 45–50, 55 or more, no statutory limit (0), unknown (98, 99, or no striking-vehicle link) | FARS `vehicle.VSPD_LIM` of the vehicle in `pedestrian.str_veh` | at crash record | 45–50 mph 42.9%, 35–40 mph 29.4%, 30 or less 12.9%, 55 or more 8.2%, **unknown 6.2%**, no statutory limit 0.4% |
| `light` | daylight (LGT_COND 1), dark, not lighted (2), dark, lighted (3), dawn or dusk (4–5), dark, lighting unknown (6), unknown (7–9) | FARS `accident.LGT_COND` | at crash record | dark, lighted 47.7%, dark, not lighted 29.6%, daylight 17.0%, dawn or dusk 4.1%, dark, lighting unknown 1.4%, unknown 0.3% |
| `crossing_location` | at intersection (PEDLOC 1), intersection-related (2), not at intersection (3), non-trafficway (4), unknown (9 or no typing record) | FARS `pbtype.PEDLOC` | at crash record (PBCAT typing is part of the FARS case) | not at intersection 72.2%, at intersection 17.4%, intersection-related 9.6%, non-trafficway 0.6%, unknown 0.1% |
| `time_of_day` | late night (0–5), morning (6–9), midday (10–15), evening (16–19), night (20–23), unknown (HOUR 99) | FARS `accident.HOUR` | at crash record | night 39.2%, evening 22.2%, late night 20.9%, morning 10.0%, midday 7.7% |

Rules that follow from Week 6, issue 1, and are enforced in code: a death whose value is unknown keeps the item `variable=unknown` in its transaction, so it stays in every support denominator; but **no reported pattern may contain an `=unknown` item**, on either side of a rule. Nothing is imputed.

### 3.2 Stratifiers (never items)

| Variable | Use in this experiment | Source | Why not an item |
|---|---|---|---|
| `year` | the split (section 4); per-year stability table | `source_file` → `crash.year` | it is the experimental design, not a roadway condition |
| `county_fips`, `county_name` | the one subgroup analysis: the five counties with the most 2020–2024 person-years (Miami-Dade, Broward, Palm Beach, Hillsborough, Orange, from `v_county_rate`) against the other 62 | FARS `accident.COUNTY`; Census Vintage 2025 for person-years | the question asks *which counties* concentrate each pattern (Objective 3); counties are where patterns are reported, not what they are made of |
| `alcohol_stratum` | sensitivity check only: do the top patterns hold among deaths with "no alcohol reported"? Printed next to the unknown share (35–42% per fit year) | FARS `person.DRINKING` | proposal §10: a victim attribute, not a roadway condition; too incomplete to split cleanly (Week 6 issue 1 (f)) |
| `age_group`, `hit_and_run` | available for error analysis in Week 11 (for example, is a failed pattern concentrated among hit-and-run deaths?) | FARS `person.AGE`, `vehicle.HIT_RUN` | same reason: they describe the people, not the road |

### 3.3 Excluded, and why

| Excluded | Reason |
|---|---|
| `walkability` (EPA National Walkability Index) | the block-group join is not built (Week 8, risk 2); the item reads `unknown` for 100% of rows, so it can carry no pattern. Excluding it is the honest option; a half-built item would bias support toward geocoded crashes |
| `crosswalk`, `junction`, `crash_group`, `vehicle_class`, `day_type` | not among the five conditions the central question names. Adding them would multiply the pattern space (more comparisons, more chance findings, Tan et al. ch. 10) and make the top-K list harder to pre-register. They stay in the view for the dashboard and for later exploratory work, which will be labelled as such |
| `latitude`, `longitud`, `st_case`, `per_no` | identifiers and quasi-identifiers; never leave the local database (proposal, ethics section). No file under `docs/` produced by this experiment contains them |
| `RACE`, `HISPANIC` | not loaded (proposal) |
| County population, `v_county_rate` | the Vintage 2025 estimates were published in 2026, after every crash in the data. They are used only to *name* the large-county subgroup (a fixed list of five), never as a feature |
| Anything from the 2024 file | the hold-out. The code filters by year in SQL and asserts the maximum year read in `tune` is 2023 |

**One known, bounded contamination, disclosed.** The bin edges of `speed_bin` and `time_of_day` and the code groupings were fixed in Week 6 from the pooled 2020–2024 *marginal* frequencies (one variable at a time). The experiment measures *joint* structure, which marginal binning does not look at, and the bins were frozen four weeks before this design; still, 2024 marginals had been seen when the bins were chosen. This is stated here so that Week 11 can weigh it; it is not a reason to re-bin now, which would be a worse form of tuning.

## 4. Training, validation and test strategy

| Split | Years | In-scope deaths | What it is used for |
|---|---|---|---|
| **Training** | 2020, 2021, 2022 (Final files) | 1,906 | mining the candidate patterns for each grid point of section 5 |
| **Validation** | 2023 (Final file) | 625 | choosing the two hyperparameters (minimum support, minimum lift) by the pre-committed rule in section 5; nothing else |
| **Final fit** | 2020–2023 | 2,531 | re-mining once, with the locked parameters, to produce the pattern list that is tested |
| **Test** | 2024 (Annual Report File, provisional) | 522 | read once, by one script stage, after the parameters were locked and the code committed; every metric of Week 11 comes from this one read |

**Why a split by year and not a random split.** Three dependencies in the data make a random split of deaths wrong, and all three are respected by a split on `year`:

1. **Time.** The decision is prospective: patterns from past years guide next year's funding. A random split would let 2024 deaths teach the miner about 2024, and would hide code drift (the 2024 file has ten times the unknown `RUR_URB` rate of any Final year, Week 6 issue 2). Evaluating forward in time is the only test that resembles the use.
2. **Group.** Deaths from one crash share every crash-level item. A random split by death would put one victim of a two-victim crash in training and the other in test, and the "replication" would be the same scene seen twice. Years never split a crash.
3. **Geography** is *not* used for the split, deliberately: counties are an output of the question (which counties concentrate each pattern), so a county-grouped split would test the wrong generalisation. Geography enters as a subgroup analysis in the test year instead (section 3.2).

**Why 2024 is the test year, despite being provisional.** The proposal and Week 6 (issue 2) fixed 2024 as the temporal hold-out and promised to label its result provisional. The Annual Report File has 13.7% fewer deaths than 2023 and more unknown codes; Week 11 reports this as a limitation and shows the unknown shares side by side. When NHTSA publishes the 2024 Final file, the pipeline reloads it with one command (Week 7 §6.5) and the `test` stage runs again, with the rerun and its reason recorded in `test_runs.log`. Both results will then be reported.

**Why a single validation year rather than cross-validation.** With four Final years there are three sensible forward splits at most, and the hyperparameter grid is nine points. Rolling-origin validation (train 2020 → validate 2021, …) would select parameters on 588–674 deaths per fold and leave 2024 untouched either way; it is a reasonable refinement but a second procedure to pre-register. One forward split keeps the protocol short enough to be followed exactly, and the stability table (support of every top pattern in each of 2020, 2021, 2022, 2023 separately) covers the "does it hold across years" question that cross-validation would answer.

## 5. Baseline and candidate method

### 5.1 Baseline: statistical independence

The baseline is the simplest model of the five conditions that a planner could hold: they are unrelated. Under independence, the expected share of deaths carrying an itemset *X* = {x₁, …, xₖ} is the product of the single-item shares, *s(X)* = ∏ *s(xᵢ)*, measured on the fit years. It is the reference against which lift is defined (Tan et al., §5.7.1: interest factor = observed support / expected support under independence), and it predicts every itemset's hold-out support from marginals alone. It is meaningful because it is exactly what the Week 6 single-variable frequency tables already give a planner; if the mined patterns cannot beat it, they add nothing to those tables.

### 5.2 Candidate: FP-Growth closed itemsets ranked by lift

1. **Transactions.** Each in-scope death is one transaction of five items `variable=value` (section 3.1), the binarisation of categorical attributes into asymmetric binary items (Tan et al., §6.1; discretization of HOUR and VSPD_LIM, §6.2, done in the view).
2. **Frequent itemsets.** FP-Growth (`mlxtend.frequent_patterns.fpgrowth`), minimum support from the grid, maximum length 4, minimum length 2 (Tan et al., §5.6). FP-Growth and Apriori return the same itemsets; FP-Growth is used because it does not generate candidates, which matters little at 2,531 transactions and is chosen for consistency with the proposal.
3. **Compaction.** Keep closed itemsets only (§5.4): an itemset is dropped if a frequent proper superset has the same support count.
4. **Unknowns.** Drop any itemset containing an `=unknown` item (Week 6 issue 1).
5. **Interestingness.** Lift of an itemset = support / product of its items' supports on the same fit rows (§5.7.1, extended beyond pairs as in §5.7.2). Keep lift ≥ minimum lift from the grid.
6. **Ranking and K.** Sort by lift descending, then support descending, then itemset text; keep the top K = 20 (K = 10 reported as a secondary cut). The candidate's prediction of a pattern's 2024 share is its 2020–2023 support.
7. **Flag, not filter: patterns expected by construction.** An itemset whose items all come from `light` and `time_of_day` (daylight with midday, dark with night) is true because of the sun, not because of the road; the text calls such high-lift patterns uninteresting (§5.7). They stay in the primary top-K (the ranking rule is fixed) but carry the flag `expected_by_construction` in every table, and the count of flagged patterns in the top-K is reported.
8. **Secondary list, pre-specified after tuning and before the test run.** The fit-years pattern list showed that lift ranks the light-and-time pairs first. So a second cut is defined here, before 2024 was read: among the patterns passing the locked thresholds, keep those with at least one item from `road_class`, `speed_bin` or `crossing_location`, rank by the same rule, take the top K = 20 ("roadway top-K"), and report the same metrics for it. It is a secondary analysis and is labelled as such wherever it appears; the primary metric is still computed on the unfiltered top-K.
9. **Rules for planners.** For each top-K itemset, every rule with a single-item consequent, with confidence and rule lift on the fit rows (§5.3). Antecedents cannot contain unknowns because itemsets cannot.

### 5.3 Hyperparameters, grid and selection rule, pre-committed

| Hyperparameter | Grid | Why these values |
|---|---|---|
| minimum support | 3%, 5%, 8% of fit transactions | 3% of 1,906 training deaths is 57 deaths, the smallest count a planner would act on; 8% keeps only broad patterns. The Week 6 verification test already requires every single item to have ≥ 1% support |
| minimum lift | 1.0, 1.2, 1.5 | 1.0 = everything above independence; 1.5 = a 50% excess, a conservative bar at this sample size |
| K | 20 (secondary 10) | fixed, not tuned: the length of a list a planning memo can carry |
| maximum itemset length | 4 | fixed: a 5-item pattern is a full profile of one death, too sparse to replicate |

**Selection rule (run by the `tune` stage, which never sees 2024):** mine on 2020–2022 at each of the nine grid points; score each by the candidate's primary metric on 2023 (section 6.1) at K = 20; choose the point with the lowest score among those that yield at least 20 patterns; break ties toward the larger minimum support, then the larger minimum lift. If no grid point yields 20 patterns, take the one with the most and record a warning. The chosen values are written to [`analysis/locked_params.json`](../analysis/locked_params.json) together with the Git commit, the configuration hash and the transaction-file hash, and the `test` stage refuses to run without that file.

**Locked parameters (filled in by `tune`, before `test` ran):** minimum support **3%**, minimum lift **1.5**, K = 20, maximum length 4. Selected on 2023 from the nine-point grid (`docs/evidence/week10/tuning_grid.csv`): at K = 20 the candidate's validation MAE was 0.80 pp at 3% support, 1.04 pp at 5% and 1.52 pp at 8% (baseline 2.83 / 2.70 / 2.69 pp); within one support level the top 20 by lift are the same at every minimum lift once 20 patterns pass, so the tie rule chose 1.5. The 2024 rows were never read: the tune log records "max year read 2023".

### 5.4 The permutation null (checks that the candidate is not finding noise)

Swap randomisation (Tan et al., ch. 10, statistical testing for association patterns): permute each item variable's column independently across the fit transactions, which preserves every single-item support and every transaction's length but destroys all joint structure; re-mine with the locked parameters; repeat 500 times with a fixed seed. The number of patterns passing the thresholds and the largest lift in the real data are compared with their null distributions. If the real data produced no more patterns than the shuffled data, the candidate would be reporting chance.

## 6. Metrics, reproducibility, seeds and versions

### 6.1 Primary metric

**MAE_pp**: over the top-K patterns, the mean absolute difference, in percentage points of in-scope deaths, between the share a method *predicted* for the hold-out year and the share *observed* there. Computed for the candidate (prediction = 2020–2023 support) and the baseline (prediction = product of 2020–2023 marginals) on the same K patterns; the comparison of interest is the difference, with its interval.

Why this metric and not confidence, lift or a count of "significant" rules: the planner's decision uses a pattern's *share of deaths* to size and rank countermeasures. Over-predicting a share funds a programme against fewer deaths than claimed; under-predicting hides a target. Both errors cost, roughly symmetrically, in percentage points of deaths, which is what MAE in percentage points measures. A metric computed only on the fit years (confidence, lift) cannot say how the claim fares next year, and a count of significant rules rewards the method for finding many patterns rather than true ones.

### 6.2 Secondary metrics (reported, not optimised)

| Metric | Definition | What it tells the planner |
|---|---|---|
| replication rate | share of top-K patterns with 2024 support ≥ minimum support and 2024 lift > 1 | how many of the listed patterns are still there, in kind |
| signed bias (pp) | mean of (predicted − observed) | whether the method systematically over- or under-states shares |
| rank agreement | Spearman correlation between fit-years lift and 2024 lift over the top-K | whether the *order* of the list survives, which is what "fund first" needs |
| coverage | share of 2024 in-scope deaths that carry at least one top-K pattern | how much of the problem the list addresses at all |
| stability by year | each pattern's support in 2020, 2021, 2022, 2023 separately, and a flag for ≥ minimum support in all four (the proposal's four-of-five-years test, with 2024 reported apart) | whether a pattern is a steady feature or one year's spike |

### 6.3 Uncertainty

Every metric comes with a 95% interval from a **cluster bootstrap by crash** (resample the 2024 crashes with replacement, keep all their deaths; 1,000 resamples), so that the 0.8% of shared scenes do not count as independent evidence. Each pattern's observed 2024 share gets a Wilson score interval. The permutation null gives one-sided p-values for the pattern count and the maximum lift.

### 6.4 Reproducibility controls

| Control | Where |
|---|---|
| Inputs pinned | six raw files by SHA-256 in `pipeline/sources.csv`; the load is gated on them (G1) and reconciled against counts (G3, G5, G6) |
| Transactions are a view, not a copy | all binning in `v_ped_transactions`; the `prepare` stage writes the transactions to `data/interim/experiment/transactions.csv` (git-ignored) and records its SHA-256 in every later log and in `locked_params.json` |
| Experiment settings in one file | `analysis/experiment_config.json`; its SHA-256 is recorded in every log |
| Tuning cannot see the test year | SQL filter by year plus an assertion in `tune` |
| Test runs once | `test` requires `locked_params.json` with a commit hash, refuses to overwrite its evidence directory without `--force "<reason>"`, and appends every invocation to `docs/evidence/week11/test_runs.log` |
| Deterministic output | FP-Growth is deterministic; all tables sorted; seeds fixed (below); no dictionary-order dependence |
| Provenance in every log | Git commit and dirty flag, PostgreSQL version, Python and package versions, seeds, hashes, in `prepare_run.log`, `tune_run.log`, `test_run.log` |
| Runs without the real data | the same three stages run in CI on the synthetic database (`docs/evidence/week10_synthetic/`, `week11_synthetic/`), with their own locked file so they can never overwrite the real one |
| Exact package versions | `requirements.lock` (`pip freeze` of the machine that produced the evidence), closing the Week 9 §5.5 gap; `requirements.txt` keeps the minimums for CI |

### 6.5 Random seeds and software versions

| | |
|---|---|
| Seeds | bootstrap 20262024; permutation 20262025 (in `experiment_config.json`). FP-Growth itself uses none |
| Python | 3.14.3 (Windows 10), the machine that holds the real database; CI runs 3.11 on `ubuntu-24.04` |
| Packages | pandas 3.0.6, numpy (see lock), scipy 1.17.1, mlxtend 0.25.0, psycopg 3.3.6, pandera 0.34.1; full list in `requirements.lock` |
| Database | PostgreSQL 16.15; the schema, views and seeds of `sql/`; the Week 7 ETL at the commit recorded in the run log |

**Commands** (from the repository root, PG* variables pointing at the project database):

```
python analysis/experiment.py prepare
python analysis/experiment.py tune
python analysis/experiment.py test
```

## 7. Methods basis

The design follows the course text (Tan, Steinbach, Karpatne, & Kumar, 2019, *Introduction to Data Mining*, 2nd ed.):

- **Chapter 5, Association Analysis: Basic Concepts and Algorithms.** Support and confidence (§5.1); frequent itemset generation and the Apriori principle (§5.2), which bounds the search at a given minimum support; rule generation from itemsets (§5.3); closed and maximal itemsets as a compact representation (§5.4); the FP-Growth algorithm (§5.6); evaluation of association patterns with objective interestingness measures, in particular the interest factor (lift) as the ratio of observed to independence-expected support, its extension beyond pairs, and the warning about Simpson's paradox (§5.7), which is why the alcohol stratum and the county subgroup are reported alongside the pooled result rather than hidden in it; the effect of skewed support distributions (§5.8), the reason the five item variables were grouped into a few values each in Week 6.
- **Chapter 6, Association Analysis: Advanced Concepts.** Handling categorical attributes by binarisation into items, and continuous attributes by discretisation into bins fixed in advance (§6.1–6.2).
- **Chapter 3, Classification: Basic Concepts and Techniques**, for the parts of experimental method that are not specific to classification: the separation of training, validation and test data, model selection on a validation set rather than on the test set, and the holdout method of evaluation (§3.4–3.6). The validation year here plays the role the text gives a validation set: choosing hyperparameters without touching the test data.
- **Chapter 10, Avoiding False Discoveries.** Statistical testing of association patterns by randomisation (swap randomisation preserving row and column sums), the multiple-comparisons problem when many patterns are tested at once, and the recommendation to keep the hypothesis space small and pre-specified, which is why the item set is limited to the five variables of the question and K is fixed in advance.
- **Chapter 2, Data**, for the data-quality handling carried over from Weeks 6–7 (coded missing values kept as explicit items, no imputation, no silent row drops).

## 8. Completion criteria

| Criterion | Where it is met |
|---|---|
| The method fits the project question | §1–2: the question asks for *combinations* of five named conditions and where they concentrate; frequent itemsets with lift are the direct formalisation, and the hold-out test turns "most frequently characterize" into a checkable claim about next year |
| The split reflects dependencies (time, group, geography) | §4: forward split by year handles time and keeps every crash whole; geography is deliberately a subgroup, not a split, with the reason given |
| Unavailable future information is excluded | §3.3: 2024 excluded from mining and tuning by SQL filter plus assertion; population estimates used only to name a fixed subgroup; the one bounded contamination (Week 6 bins chosen on pooled marginals) is disclosed rather than hidden |
| A meaningful baseline is defined | §5.1: statistical independence, which is both the reference of the lift measure and what the existing single-variable tables already give a planner |
| Preprocessing and training can be reproduced | §6.4–6.5: pinned inputs, the view as the single source of transactions, hashed config and transactions, locked parameters with commit hash, seeds, `requirements.lock`, and the same stages running in CI on synthetic data |
| Realisation follows the course text | §7, section by section |

---

## Sources and AI assistance

- Tan, P.-N., Steinbach, M., Karpatne, A., & Kumar, V. (2019). *Introduction to data mining* (2nd ed.). Pearson. Chapters 2, 3, 5, 6 and 10 as cited in section 7.
- Raschka, S. (2018). MLxtend: Providing machine learning and data science utilities and extensions to Python's scientific computing stack. *Journal of Open Source Software, 3*(24), 638. (The `fpgrowth` implementation used.)
- National Highway Traffic Safety Administration. (2026). *FARS National CSV files 2020–2024*. https://static.nhtsa.gov/nhtsa/downloads/FARS/
- U.S. Census Bureau. (2026). *County population totals 2020–2025, Vintage 2025*. https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html
- This repository: `docs/Week6_Data_Cleaning_Plan_Shkirpan.md` (bins, unknown rule, the provisional 2024 file), `docs/Week7_Pipeline_Shkirpan.md` (gates, reload by year), `docs/Week8_Midpoint_Shkirpan.md` (risk register, schedule), `sql/04_views.sql`.

I used Claude (Anthropic), an AI assistant, to help draft this design and to write the experiment code in `analysis/` from it. The question, the five conditions, the hold-out year, the unknown-item rule, the bins and the ethics rules come from my approved proposal and my Week 4–9 work; the choices made here (the split, the independence baseline, the primary metric, the grid and the selection rule) were fixed in this document and in `analysis/experiment_config.json` before any pattern was mined on the real data. I reviewed the generated material and I am responsible for the content.
