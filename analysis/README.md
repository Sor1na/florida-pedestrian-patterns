# analysis/ - Weeks 10-11 experiment

`experiment.py` mines closed association patterns among in-scope pedestrian deaths (one row of
`v_ped_transactions` = one death, five items per row) and tests them forward in time against an
independence baseline. Every setting is read from the pre-registered `experiment_config.json`.

## Stages

| stage | reads | writes |
|---|---|---|
| `prepare` | the whole view + `v_county_rate` | `transactions.csv`, `transactions.sha256`, `county_group.csv` (git-ignored, `data/interim/experiment/`), `prepare_run.log` |
| `tune` | the database, `WHERE year <= 2023` only | `tuning_grid.csv`, `tune_run.log`, locked params (`analysis/locked_params.json`) |
| `test` | the prepared CSV + locked params | `results_summary.json`, `patterns_topk`, `patterns_rules`, `stability_by_year`, `subgroup_county`, `sensitivity_alcohol`, `unknown_share_by_year`, `permutation_null`, `permutation_summary`, `error_analysis`, `baseline_vs_candidate` (.csv), `test_run.log`, `test_runs.log` |

`tune`: FP-Growth on 2020-2022, closed itemsets of length 2-4 without unknown items, lift >= min_lift, top-K
by lift; each grid point is scored on 2023 (MAE in percentage points, candidate vs independence baseline).
Selection: lowest candidate MAE among points with >= K patterns; ties to larger min_support, then larger min_lift;
if no point reaches K, the point with the most patterns and a WARNING.
`test`: refit on 2020-2023 with the locked values, evaluate on 2024 (provisional ARF): MAE, bias, replication,
Spearman, coverage, crash-level cluster bootstrap (B = 1000), Wilson intervals, swap-randomisation null,
per-year stability, county-group and alcohol subgroups, unknown-share table, rules, error analysis.

## Commands

Connection: PG* environment variables (or `--dsn`), as in `pipeline/etl.py`. Set `PYTHONDONTWRITEBYTECODE=1`.

Synthetic (committed evidence in `docs/evidence/week10_synthetic/` and `week11_synthetic/`):

    export PGDATABASE=ped_safety
    S="--locked data/interim/experiment/locked_params_synthetic.json --transactions data/interim/experiment/transactions_synthetic.csv"
    python analysis/experiment.py prepare --evidence-dir docs/evidence/week10_synthetic $S
    python analysis/experiment.py tune    --evidence-dir docs/evidence/week10_synthetic $S
    python analysis/experiment.py test    --evidence-dir docs/evidence/week11_synthetic $S --permutations 50

Real data (defaults: transactions in `data/interim/experiment/`, evidence `docs/evidence/week10` for
prepare/tune and `docs/evidence/week11` for test, locked params `analysis/locked_params.json`):

    export PGDATABASE=ped_real
    python analysis/experiment.py prepare
    python analysis/experiment.py tune
    git add analysis/locked_params.json docs/evidence/week10 && git commit   # lock before looking at 2024
    python analysis/experiment.py test                                       # once

CI runs the three stages on `ped_safety_week7` with the synthetic paths and `--permutations 50`.

## Leakage protocol (enforced in code)

- `tune` filters `year <= validation_year` in SQL and asserts that no later year was read.
- `test` refuses to run if the locked params are missing or carry no `git_commit`, if the config changed since
  tuning, or if its 2020-2023 rows differ from the rows `tune` read (content hash in the locked file).
- `test` runs once per evidence dir; a second run needs `--force "<reason>"`. Every invocation (time, commit,
  dirty flag, reason, outcome) is appended to `<evidence_dir>/test_runs.log`.
- `tune` refuses to write `analysis/locked_params.json` from a non-default transactions file or a
  `*_synthetic` evidence dir, so synthetic runs cannot replace the real locked parameters.
- Deterministic: fixed seeds from the config, exact integer lift, sorted outputs.
- Privacy: files under `docs/` hold aggregates only (no case numbers, person numbers or coordinates).
