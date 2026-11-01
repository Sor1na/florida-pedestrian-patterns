#!/usr/bin/env python3
"""
experiment.py - Weeks 10-11: closed association patterns among Florida pedestrian deaths, tested forward in time.

    python analysis/experiment.py prepare            # view -> data/interim/experiment/transactions.csv (+ sha256, county groups)
    python analysis/experiment.py tune               # grid search train 2020-2022 -> validation 2023; writes locked params
    python analysis/experiment.py test               # ONE run: fit 2020-2023 with the locked params, evaluate on 2024

Every setting comes from analysis/experiment_config.json (pre-registered). Methods (Tan, Steinbach, Karpatne,
Kumar, Introduction to Data Mining, 2nd ed.):
  * frequent itemsets by FP-Growth (section 5.6), mlxtend.frequent_patterns.fpgrowth;
  * closed frequent itemsets (section 5.4): X is closed if no frequent proper superset has the same support count;
  * lift / interest factor relative to statistical independence (section 5.7): supp(X) / prod supp(x_i);
  * significance by swap randomisation (chapter 10): each item column permuted independently, which keeps every
    item support and every transaction length and destroys the associations.

Unit = one row of v_ped_transactions (one death). Each row gives exactly one item per item variable, including
'variable=unknown', so support denominators keep every death; any itemset holding an unknown item is dropped
(Week 6 cleaning plan, section 4, issue 1). Closedness is judged among the known-item itemsets only.

Reporting flags (config `candidate`): an itemset whose items all come from `expected_by_construction_variables`
(light, time_of_day) is flagged `expected_by_construction`: sunlight makes daylight<->midday and dark<->night true by
construction, so such patterns carry no roadway information for a planner - high lift, but uninteresting in the
sense of Tan et al. section 5.7. A secondary "roadway top-K" list (pre-specified after tuning, before the test run)
keeps only patterns with at least one item from `roadway_variables` and is ranked by the same rule.

Leakage protocol: `tune` reads the database with `year <= validation_year` in SQL and asserts it; `test` refuses to
run without locked params carrying a git commit, refuses a second run on the same evidence dir unless --force
REASON, checks that its fit rows are the rows tune saw, and appends every invocation to test_runs.log.
Connection settings: PG* environment variables (default database ped_safety) or --dsn, as in pipeline/etl.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "analysis" / "experiment_config.json"
DEFAULT_LOCKED = ROOT / "analysis" / "locked_params.json"
DEFAULT_OUT = ROOT / "data" / "interim" / "experiment"
COLUMNS = ["year", "st_case", "per_no", "county_fips", "county_name", "road_class", "speed_bin", "light",
           "crossing_location", "crosswalk", "time_of_day", "day_type", "junction", "crash_group", "vehicle_class",
           "hit_and_run", "age_group", "walkability", "alcohol_stratum"]
SEP = " & "


# --------------------------------------------------------------------------- bookkeeping
class Log:
    """Timestamped lines to the console and to <evidence_dir>/<stage>_run.log."""

    def __init__(self, path: Path, mode: str = "w"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, mode, encoding="utf-8")

    def __call__(self, msg: str = "") -> None:
        for part in str(msg).split("\n"):
            text = f"{datetime.now().astimezone().isoformat(timespec='milliseconds')} | {part}"
            print(text, flush=True)
            self.fh.write(text + "\n")
        self.fh.flush()


def git_commit() -> tuple[str | None, bool]:
    """HEAD commit and whether tracked files outside docs/evidence differ from it (as in pipeline/etl.py)."""
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", ".", ":!docs/evidence"],
                                    cwd=ROOT, capture_output=True, text=True).stdout.strip())
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False


def conninfo(args) -> str:
    if args.dsn:
        return args.dsn
    return "" if os.environ.get("PGDATABASE") else "dbname=ped_safety"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows_sha256(df: pd.DataFrame) -> str:
    """Content hash of rows (all values as text, sorted by key) - identical for the database read and the CSV read."""
    d = df[COLUMNS].astype(str).sort_values(["year", "st_case", "per_no"], key=lambda s: s.astype(int)
                                            if s.name in ("year", "st_case", "per_no") else s)
    return hashlib.sha256(d.to_csv(index=False, lineterminator="\n").encode()).hexdigest()


def header(log: Log, args, cfg_path: Path, stage: str) -> dict:
    """Versions, server, commit, hashes and seeds at the top of every stage log."""
    import mlxtend
    import scipy
    sha, dirty = git_commit()
    try:
        import psycopg
        with psycopg.connect(conninfo(args)) as conn:
            server = conn.execute("SHOW server_version").fetchone()[0]
            dbname = conn.info.dbname
    except Exception as exc:                       # test does not need the database
        server, dbname = f"not reachable ({type(exc).__name__})", "-"
    info = {"stage": stage, "git_commit": sha, "git_dirty": dirty, "config_sha256": sha256_file(cfg_path),
            "database": dbname}
    log(f"stage {stage}; argv: {' '.join(sys.argv[1:])}")
    log(f"python {platform.python_version()} on {platform.platform()}; pandas {pd.__version__}; numpy {np.__version__}; "
        f"scipy {scipy.__version__}; mlxtend {mlxtend.__version__}")
    log(f"PostgreSQL server_version {server}; database {dbname}")
    log(f"git commit {sha or 'unknown'}; dirty={dirty}; config {cfg_path.name} sha256 {info['config_sha256']}")
    return info


def companion(transactions: Path, kind: str) -> Path:
    """county_group*.csv and transactions*.sha256 live next to the transactions file and share its suffix."""
    if kind == "sha":
        return transactions.with_suffix(".sha256")
    return transactions.with_name(transactions.name.replace("transactions", "county_group", 1))


# --------------------------------------------------------------------------- items and mining
def item_matrix(df: pd.DataFrame, item_vars: list[str]) -> pd.DataFrame:
    """One-hot boolean table, one column per 'variable=value' item (unknown items included)."""
    cols = {}
    for var in item_vars:
        for val in sorted(df[var].unique()):
            cols[f"{var}={val}"] = (df[var] == val).to_numpy()
    return pd.DataFrame(cols, index=df.index).reindex(sorted(cols), axis=1)


def contains(df: pd.DataFrame, items: tuple[str, ...]) -> np.ndarray:
    """Boolean mask of the rows that contain every item of the itemset."""
    mask = np.ones(len(df), dtype=bool)
    for it in items:
        var, val = it.split("=", 1)
        mask &= (df[var] == val).to_numpy()
    return mask


def item_key(cfg: dict):
    order = {v: i for i, v in enumerate(cfg["item_variables"])}
    return lambda it: (order[it.split("=", 1)[0]], it)


def label(items: tuple[str, ...]) -> str:
    return SEP.join(items)


def mine(fit: pd.DataFrame, cfg: dict, min_support: float, min_lift: float) -> pd.DataFrame:
    """FP-Growth (Tan 5.6) -> drop unknown -> closed (5.4) -> length 2..4 -> lift (5.7) >= min_lift, ranked.

    Lift is computed from integer counts in one division, so equal patterns tie exactly and the ranking is
    deterministic: lift desc, support desc, itemset text asc (items in item_variables order)."""
    from mlxtend.frequent_patterns import fpgrowth
    c = cfg["candidate"]
    unknown = "=" + cfg["unknown_label"]
    n = len(fit)
    onehot = item_matrix(fit, cfg["item_variables"])
    freq = fpgrowth(onehot, min_support=min_support, use_colnames=True, max_len=c["max_itemset_len"])
    single = onehot.sum(axis=0).astype(int).to_dict()
    key = item_key(cfg)
    counts: dict[tuple[str, ...], int] = {}
    for sup, items in zip(freq["support"], freq["itemsets"]):
        if any(it.endswith(unknown) for it in items):
            continue
        counts[tuple(sorted(items, key=key))] = int(round(sup * n))
    not_closed = set()
    for items, cnt in counts.items():              # an immediate superset with the same count suffices (anti-monotone)
        if len(items) >= 2:
            for sub in combinations(items, len(items) - 1):
                if counts.get(sub) == cnt:
                    not_closed.add(sub)
    construction = set(c["expected_by_construction_variables"])
    rows = []
    for items, cnt in counts.items():
        k = len(items)
        if k < c["min_itemset_len"] or items in not_closed:
            continue
        denom = int(np.prod([single[it] for it in items], dtype=object))
        lift = (cnt * n ** (k - 1)) / denom
        if lift >= min_lift:
            rows.append({"itemset": label(items), "items": items, "length": k, "fit_count": cnt,
                         "fit_support": cnt / n, "baseline_support": denom / n ** k, "fit_lift": lift,
                         "expected_by_construction": all(it.split("=", 1)[0] in construction for it in items)})
    out = pd.DataFrame(rows, columns=["itemset", "items", "length", "fit_count", "fit_support", "baseline_support",
                                      "fit_lift", "expected_by_construction"])
    return out.sort_values(["fit_lift", "fit_support", "itemset"], ascending=[False, False, True]).reset_index(drop=True)


def roadway_only(pats: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Secondary list: patterns with at least one item from roadway_variables, ranking order kept."""
    road = set(cfg["candidate"]["roadway_variables"])
    keep = [any(it.split("=", 1)[0] in road for it in items) for items in pats["items"]]
    return pats[keep].reset_index(drop=True)


def holdout_stats(top: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    """Observed hold-out count, support and lift of each pattern."""
    n = len(hold)
    obs = []
    for items in top["items"]:
        cnt = int(contains(hold, items).sum())
        singles = [int(contains(hold, (it,)).sum()) for it in items]
        denom = int(np.prod(singles, dtype=object))
        lift = cnt * n ** (len(items) - 1) / denom if denom else np.nan
        obs.append((cnt, cnt / n if n else np.nan, lift))
    return pd.DataFrame(obs, columns=["obs_count", "obs_support", "obs_lift"], index=top.index)


def metrics(top: pd.DataFrame, hold: pd.DataFrame, min_support: float) -> dict:
    """MAE_pp (primary), signed bias, replication rate, Spearman of lifts, coverage, for both methods."""
    from scipy.stats import spearmanr
    if top.empty:
        return {"k": 0, "mae_pp_candidate": np.nan, "mae_pp_baseline": np.nan, "mae_pp_difference": np.nan,
                "signed_bias_pp_candidate": np.nan, "signed_bias_pp_baseline": np.nan, "replication_rate": np.nan,
                "spearman_rank": np.nan, "coverage": np.nan}
    core = top[["items", "fit_support", "baseline_support", "fit_lift"]]
    t = core.join(holdout_stats(core, hold))
    err_c = (t["fit_support"] - t["obs_support"]) * 100
    err_b = (t["baseline_support"] - t["obs_support"]) * 100
    replicated = (t["obs_support"] >= min_support) & (t["obs_lift"] > 1)
    rho = np.nan
    if len(t) >= 3 and t["fit_lift"].nunique() > 1 and t["obs_lift"].nunique() > 1:
        rho = float(spearmanr(t["fit_lift"], t["obs_lift"], nan_policy="omit").statistic)
    covered = np.zeros(len(hold), dtype=bool)
    for items in t["items"]:
        covered |= contains(hold, items)
    return {"k": int(len(t)), "mae_pp_candidate": float(err_c.abs().mean()), "mae_pp_baseline": float(err_b.abs().mean()),
            "mae_pp_difference": float(err_c.abs().mean() - err_b.abs().mean()),
            "signed_bias_pp_candidate": float(err_c.mean()), "signed_bias_pp_baseline": float(err_b.mean()),
            "replication_rate": float(replicated.mean()), "spearman_rank": rho, "coverage": float(covered.mean())}


def wilson(count: int, n: int, z: float) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (np.nan, np.nan)
    p = count / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


# --------------------------------------------------------------------------- data access
def read_db(args, where: str = "") -> pd.DataFrame:
    import psycopg
    sql = f"SELECT {', '.join(COLUMNS)} FROM v_ped_transactions {where} ORDER BY year, st_case, per_no"
    with psycopg.connect(conninfo(args)) as conn:
        cur = conn.execute(sql)
        data = cur.fetchall()
    df = pd.DataFrame(data, columns=COLUMNS)
    return df.map(lambda v: "" if v is None else str(v)).astype(str)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)[COLUMNS]


def years(df: pd.DataFrame, ys) -> pd.DataFrame:
    ys = {str(y) for y in (ys if isinstance(ys, (list, tuple)) else [ys])}
    return df[df["year"].isin(ys)].reset_index(drop=True)


# --------------------------------------------------------------------------- stage: prepare
def stage_prepare(args, cfg: dict, cfg_path: Path) -> int:
    log = Log(Path(args.evidence_dir) / "prepare_run.log")
    header(log, args, cfg_path, "prepare")
    tx = Path(args.transactions) if args.transactions else Path(args.out) / "transactions.csv"
    tx.parent.mkdir(parents=True, exist_ok=True)
    df = read_db(args)
    df.to_csv(tx, index=False, lineterminator="\n")
    digest = sha256_file(tx)
    companion(tx, "sha").write_text(f"{digest}  {tx.name}\n", encoding="utf-8")
    log(f"wrote {len(df)} rows to {tx.relative_to(ROOT) if tx.is_relative_to(ROOT) else tx}; sha256 {digest}")
    log(f"content hash of the rows (order-independent) {rows_sha256(df)}")
    for y, n in df["year"].value_counts().sort_index().items():
        log(f"  rows in {y}: {n}")
    import psycopg
    with psycopg.connect(conninfo(args)) as conn:
        cg = pd.DataFrame(conn.execute(
            "SELECT county_fips, county_name, person_years FROM v_county_rate WHERE person_years IS NOT NULL "
            "ORDER BY person_years DESC, county_fips").fetchall(), columns=["county_fips", "county_name", "person_years"])
    cg["group"] = ["five most populous" if i < 5 else "other counties" for i in range(len(cg))]
    cg.to_csv(companion(tx, "county"), index=False, lineterminator="\n")
    log("five most populous counties by 2020-2024 person-years: "
        + "; ".join(f"{r.county_name} ({r.county_fips}) {int(r.person_years)}" for r in cg.head(5).itertuples()))
    return 0


# --------------------------------------------------------------------------- stage: tune
def stage_tune(args, cfg: dict, cfg_path: Path) -> int:
    log = Log(Path(args.evidence_dir) / "tune_run.log")
    info = header(log, args, cfg_path, "tune")
    tx, locked = Path(args.transactions), Path(args.locked)
    if locked.resolve() == DEFAULT_LOCKED.resolve() and (tx.resolve() != (DEFAULT_OUT / "transactions.csv").resolve()
                                                         or Path(args.evidence_dir).name.endswith("_synthetic")):
        log("REFUSED: analysis/locked_params.json is reserved for the real-data run (default transactions path, "
            "non-synthetic evidence dir). Pass --locked elsewhere for this run.")
        return 2
    sp = cfg["split"]
    df = read_db(args, f"WHERE year <= {int(sp['validation_year'])}")       # the test year is never read here
    assert df["year"].astype(int).max() <= sp["validation_year"] < sp["test_year"], "tune read a test-year row"
    log(f"read {len(df)} rows from the database with year <= {sp['validation_year']}; max year read "
        f"{df['year'].astype(int).max()}")
    fit, val = years(df, sp["train_years"]), years(df, sp["validation_year"])
    log(f"train {sp['train_years']}: {len(fit)} rows; validation {sp['validation_year']}: {len(val)} rows")
    c, k = cfg["candidate"], cfg["candidate"]["top_k"]
    rows = []
    for ms in c["grid"]["min_support"]:
        for ml in c["grid"]["min_lift"]:
            pats = mine(fit, cfg, ms, ml)
            m = metrics(pats.head(k), val, ms)
            rows.append({"min_support": ms, "min_lift": ml, "n_patterns": len(pats), "k_evaluated": m["k"],
                         "n_topk_expected_by_construction": int(pats.head(k)["expected_by_construction"].sum()),
                         "mae_pp_candidate": m["mae_pp_candidate"], "mae_pp_baseline": m["mae_pp_baseline"],
                         "replication_rate": m["replication_rate"]})
    grid = pd.DataFrame(rows)
    eligible = grid[grid["n_patterns"] >= k]
    if eligible.empty:
        log(f"WARNING: no grid point yields >= {k} patterns; taking the point with the most patterns "
            f"(ties: lower MAE, larger min_support, larger min_lift)")
        pool = grid[grid["n_patterns"] == grid["n_patterns"].max()]
    else:
        pool = eligible
    pool = pool.assign(_mae=pool["mae_pp_candidate"].round(12).fillna(np.inf))
    best = pool.sort_values(["_mae", "min_support", "min_lift"], ascending=[True, False, False]).index[0]
    grid["selected"] = grid.index == best
    ev = Path(args.evidence_dir)
    grid.to_csv(ev / "tuning_grid.csv", index=False, float_format="%.6f", lineterminator="\n")
    log("tuning grid (train -> validation, K = %d):\n%s" % (k, grid.to_string(index=False, float_format="%.4f")))
    sel = grid.loc[best]
    params = {"min_support": float(sel["min_support"]), "min_lift": float(sel["min_lift"]), "top_k": k,
              "secondary_top_k": c["secondary_top_k"], "max_len": c["max_itemset_len"],
              "n_patterns_validation": int(sel["n_patterns"]), "fewer_than_k_patterns": bool(eligible.empty),
              "git_commit": info["git_commit"], "git_dirty": info["git_dirty"],
              "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
              "config_sha256": info["config_sha256"], "database": info["database"],
              "transactions_file": tx.name,
              "transactions_sha256": sha256_file(tx) if tx.exists() else None,
              "rows_through_validation_sha256": rows_sha256(df)}
    locked.parent.mkdir(parents=True, exist_ok=True)
    locked.write_text(json.dumps(params, indent=2) + "\n", encoding="utf-8")
    log(f"selected min_support={params['min_support']}, min_lift={params['min_lift']}; wrote {locked.name}")
    return 0


# --------------------------------------------------------------------------- stage: test
def guard_test(args, ev: Path, log: Log, info: dict, df: pd.DataFrame, cfg: dict) -> dict | None:
    """Locked params must exist with a commit; config and 2020-2023 rows unchanged since tune; one run per evidence
    dir unless --force REASON. Every invocation, refused or not, is appended to test_runs.log."""
    runs = ev / "test_runs.log"
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")

    def record(status: str) -> None:
        with open(runs, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} | commit={info['git_commit']} dirty={info['git_dirty']} | forced={args.force or '-'} "
                     f"| {status}\n")
    locked = Path(args.locked)
    if not locked.exists():
        log(f"REFUSED: {locked} does not exist; run tune first"); record("refused: no locked params"); return None
    params = json.loads(locked.read_text(encoding="utf-8"))
    if not params.get("git_commit"):
        log("REFUSED: locked params have no git_commit"); record("refused: locked params without commit"); return None
    if params.get("config_sha256") != info["config_sha256"] and not args.force:
        log("REFUSED: the config changed after tuning"); record("refused: config changed"); return None
    fit_hash = rows_sha256(df[df["year"].astype(int) <= cfg["split"]["validation_year"]])
    if fit_hash != params.get("rows_through_validation_sha256"):
        if not args.force:
            log("REFUSED: the 2020-2023 rows differ from the rows tune read"); record("refused: rows changed"); return None
        log("WARNING: 2020-2023 rows differ from the rows tune read (continuing under --force)")
    previous = runs.exists() and any("| started" in ln for ln in runs.read_text(encoding="utf-8").splitlines())
    if previous and not args.force:
        log(f"REFUSED: a test already ran against {ev}; pass --force \"<reason>\" to run again")
        record("refused: second run without --force"); return None
    record("started")
    return params


def bootstrap(top: pd.DataFrame, hold: pd.DataFrame, min_support: float, b: int, seed: int, level: float) -> dict:
    """Cluster bootstrap of the hold-out year: crashes (year, st_case) drawn with replacement, all their deaths kept.

    Per-crash counts are precomputed, so each resample is a weighted sum (weights = times each crash is drawn)."""
    crash = hold["year"] + "-" + hold["st_case"]
    codes, uniq = pd.factorize(crash, sort=True)
    n_c = len(uniq)

    def per_crash(mask: np.ndarray) -> np.ndarray:
        return np.bincount(codes, weights=mask.astype(float), minlength=n_c)
    rows = per_crash(np.ones(len(hold), dtype=bool))
    pat = np.column_stack([per_crash(contains(hold, it)) for it in top["items"]])
    item_list = sorted({it for items in top["items"] for it in items})
    single = {it: per_crash(contains(hold, (it,))) for it in item_list}
    covered = np.zeros(len(hold), dtype=bool)
    for items in top["items"]:
        covered |= contains(hold, items)
    cov = per_crash(covered)
    rng = np.random.default_rng(seed)
    np.seterr(divide="ignore", invalid="ignore")
    w = rng.multinomial(n_c, np.full(n_c, 1.0 / n_c), size=b).astype(float)          # B x crashes
    n = w @ rows
    supp = (w @ pat) / n[:, None]
    sup_single = {it: (w @ v) / n for it, v in single.items()}
    lift = np.column_stack([supp[:, j] / np.prod([sup_single[it] for it in items], axis=0)
                            for j, items in enumerate(top["items"])])
    pred_c, pred_b = top["fit_support"].to_numpy(), top["baseline_support"].to_numpy()
    stats = {"mae_pp_candidate": np.abs(pred_c - supp).mean(axis=1) * 100,
             "mae_pp_baseline": np.abs(pred_b - supp).mean(axis=1) * 100}
    stats["mae_pp_difference"] = stats["mae_pp_candidate"] - stats["mae_pp_baseline"]
    stats["replication_rate"] = ((supp >= min_support) & (lift > 1)).mean(axis=1)
    stats["coverage"] = (w @ cov) / n
    lo, hi = (1 - level) / 2 * 100, (1 + level) / 2 * 100
    return {name: [float(np.percentile(v, lo)), float(np.percentile(v, hi))] for name, v in stats.items()}


def permutation_null(fit: pd.DataFrame, hold: pd.DataFrame, top: pd.DataFrame, cfg: dict, p: dict, n_perm: int,
                     seed: int, log: Log) -> pd.DataFrame:
    """Swap randomisation (Tan ch. 10): permute each item column of the fit rows independently and mine again; the
    real top-K is also scored on a hold-out year permuted the same way (null replication rate)."""
    rng = np.random.default_rng(seed)
    out, t0 = [], time.perf_counter()
    for r in range(1, n_perm + 1):
        pf, ph = fit.copy(), hold.copy()
        for var in cfg["item_variables"]:
            pf[var] = rng.permutation(pf[var].to_numpy())
            ph[var] = rng.permutation(ph[var].to_numpy())
        pats = mine(pf, cfg, p["min_support"], p["min_lift"])
        rep = metrics(top, ph, p["min_support"])["replication_rate"] if len(top) else np.nan
        out.append({"resample": r, "n_patterns": len(pats),
                    "max_lift": float(pats["fit_lift"].max()) if len(pats) else np.nan, "replication_rate": rep})
        if r % 50 == 0:
            log(f"  permutation {r}/{n_perm}: {time.perf_counter() - t0:.1f} s")
    return pd.DataFrame(out)


def rules_table(top: pd.DataFrame, fit: pd.DataFrame) -> pd.DataFrame:
    """Every single-consequent rule of each top-K itemset, with confidence and rule lift on the fit rows."""
    n, rows = len(fit), []
    for rank, items in enumerate(top["items"], start=1):
        cnt = int(contains(fit, items).sum())
        for cons in items:
            ante = tuple(it for it in items if it != cons)
            a_cnt, c_cnt = int(contains(fit, ante).sum()), int(contains(fit, (cons,)).sum())
            conf = cnt / a_cnt
            rows.append({"pattern_rank": rank, "itemset": label(items), "antecedent": label(ante), "consequent": cons,
                         "support": cnt / n, "confidence": conf, "rule_lift": conf / (c_cnt / n)})
    return pd.DataFrame(rows).sort_values(["confidence", "rule_lift", "itemset", "consequent"],
                                          ascending=[False, False, True, True]).reset_index(drop=True)


def subgroup_rows(top: pd.DataFrame, sub: pd.DataFrame, name: str, extra: dict) -> pd.DataFrame:
    st = holdout_stats(top, sub)
    return pd.DataFrame({"group": name, "n_rows": len(sub), **extra, "pattern_rank": top["rank"],
                         "itemset": top["itemset"], "expected_by_construction": top["expected_by_construction"], "predicted_candidate": top["fit_support"],
                         "predicted_baseline": top["baseline_support"], "observed_support": st["obs_support"],
                         "observed_lift": st["obs_lift"]})


def annotate(lst: pd.DataFrame, hold: pd.DataFrame, ms: float, z: float) -> pd.DataFrame:
    """Per-pattern table: rank, hold-out support/lift, Wilson interval, residuals of both methods, replication,
    and the share of the pattern's hold-out deaths that were hit-and-run (aggregate only)."""
    t = lst.copy()
    t.insert(0, "rank", range(1, len(t) + 1))
    t = t.join(holdout_stats(t, hold))
    ci = [wilson(int(c), len(hold), z) for c in t["obs_count"]]
    t["obs_wilson_low"], t["obs_wilson_high"] = [c[0] for c in ci], [c[1] for c in ci]
    t["residual_candidate_pp"] = (t["fit_support"] - t["obs_support"]) * 100
    t["residual_baseline_pp"] = (t["baseline_support"] - t["obs_support"]) * 100
    t["replicated"] = (t["obs_support"] >= ms) & (t["obs_lift"] > 1)
    t["baseline_beats_candidate"] = t["residual_baseline_pp"].abs() < t["residual_candidate_pp"].abs()
    shares = []
    for items in t["items"]:
        mask = contains(hold, items)
        shares.append(float((hold.loc[mask, "hit_and_run"] == "hit-and-run").mean()) if mask.any() else np.nan)
    t["hit_and_run_share_2024"] = shares
    return t


def list_metrics(lst: pd.DataFrame, hold: pd.DataFrame, ms: float, cfg: dict, log: Log, name: str) -> dict:
    """Metrics of one pattern list plus cluster-bootstrap CIs, logged on one line."""
    unc = cfg["uncertainty"]
    m = metrics(lst, hold, ms)
    m["ci95"] = bootstrap(lst, hold, ms, unc["bootstrap_resamples"], cfg["seeds"]["bootstrap"],
                          unc["confidence_level"]) if len(lst) else {}

    def show(key: str) -> str:
        lo_hi = m["ci95"].get(key, [np.nan, np.nan])
        return f"{m[key]:.3f} [{lo_hi[0]:.3f}, {lo_hi[1]:.3f}]"
    log(f"{name} (evaluated {m['k']}): MAE_pp candidate {show('mae_pp_candidate')}, baseline "
        f"{show('mae_pp_baseline')}, difference {show('mae_pp_difference')}; replication {show('replication_rate')}; "
        f"coverage {show('coverage')}; Spearman {m['spearman_rank']:.3f}; bias candidate "
        f"{m['signed_bias_pp_candidate']:.3f}, baseline {m['signed_bias_pp_baseline']:.3f}")
    return m


def stability(lst: pd.DataFrame, df: pd.DataFrame, sp: dict, ms: float) -> pd.DataFrame:
    """Support and lift of each pattern in every year separately; present in all fit years at min_support."""
    stab = lst[["rank", "itemset", "expected_by_construction"]].copy()
    for y in sp["final_fit_years"] + [sp["test_year"]]:
        st = holdout_stats(lst, years(df, y))
        stab[f"support_{y}"], stab[f"lift_{y}"] = st["obs_support"], st["obs_lift"]
    stab["present_in_all_fit_years"] = np.all([stab[f"support_{y}"] >= ms for y in sp["final_fit_years"]], axis=0)
    return stab


def subgroups(lst: pd.DataFrame, hold: pd.DataFrame, big: set, ms: float, cfg: dict, log: Log, tag: str):
    """County group (five most populous vs others) and alcohol sensitivity tables for one pattern list."""
    parts, summary = [], {}
    for name, part in [("five most populous", hold[hold["county_fips"].isin(big)]),
                       ("other counties", hold[~hold["county_fips"].isin(big)])]:
        part = part.reset_index(drop=True)
        parts.append(subgroup_rows(lst, part, name, {}))
        m = metrics(lst, part, ms) if len(part) else {}
        summary[name] = {"n_rows": len(part), "mae_pp_candidate": m.get("mae_pp_candidate"),
                         "mae_pp_baseline": m.get("mae_pp_baseline"), "replication_rate": m.get("replication_rate")}
        log(f"{tag}: county group '{name}' ({len(part)} test rows): MAE_pp candidate "
            f"{m.get('mae_pp_candidate', np.nan):.3f}, baseline {m.get('mae_pp_baseline', np.nan):.3f}")
    unk_alc = float((hold["alcohol_stratum"] == cfg["unknown_label"]).mean())
    clean = hold[hold["alcohol_stratum"] == "no alcohol reported"].reset_index(drop=True)
    alc = pd.concat([subgroup_rows(lst, hold, "all deaths", {"alcohol_unknown_share": unk_alc}),
                     subgroup_rows(lst, clean, "no alcohol reported", {"alcohol_unknown_share": unk_alc})])
    log(f"{tag}: alcohol sensitivity: {len(clean)} of {len(hold)} test rows 'no alcohol reported'; alcohol unknown "
        f"share {unk_alc:.3f} (not a clean split)")
    return pd.concat(parts), summary, alc


def stage_test(args, cfg: dict, cfg_path: Path) -> int:
    ev = Path(args.evidence_dir)
    log = Log(ev / "test_run.log", mode="a")
    info = header(log, args, cfg_path, "test")
    from scipy.stats import norm
    t_start = time.perf_counter()
    sp, unc, unknown = cfg["split"], cfg["uncertainty"], cfg["unknown_label"]
    tx = Path(args.transactions)
    df = read_csv(tx)
    p = guard_test(args, ev, log, info, df, cfg)
    if p is None:
        return 2
    log(f"transactions {tx.name} sha256 {sha256_file(tx)} ({len(df)} rows); locked params: min_support "
        f"{p['min_support']}, min_lift {p['min_lift']}, K {p['top_k']}, locked at commit {p['git_commit']}")
    n_perm = args.permutations or cfg["permutation_null"]["resamples"]
    log(f"seeds: bootstrap {cfg['seeds']['bootstrap']} (B={unc['bootstrap_resamples']}), permutation "
        f"{cfg['seeds']['permutation']} (N={n_perm}{' override' if args.permutations else ''})")
    fit, hold = years(df, sp["final_fit_years"]), years(df, sp["test_year"])
    log(f"fit {sp['final_fit_years']}: {len(fit)} rows; test {sp['test_year']} ({sp['test_year_release']}): {len(hold)} rows")
    k, k2, ms = p["top_k"], p["secondary_top_k"], p["min_support"]
    pats = mine(fit, cfg, ms, p["min_lift"])
    road_pats = roadway_only(pats, cfg)
    z = float(norm.ppf(0.5 + unc["confidence_level"] / 2))
    top = annotate(pats.head(k), hold, ms, z)
    road = annotate(road_pats.head(k), hold, ms, z)
    if len(top) < k:
        log(f"WARNING: only {len(top)} patterns pass the locked thresholds on the fit years (K = {k})")
    if len(road) < k:
        log(f"WARNING: only {len(road)} roadway patterns pass the locked thresholds on the fit years (K = {k})")
    log(f"patterns passing on the fit years: {len(pats)}; expected_by_construction: "
        f"{int(pats['expected_by_construction'].sum())}; roadway list: {len(road_pats)}; "
        f"expected_by_construction among the primary top-{k}: {int(top['expected_by_construction'].sum())}")

    summary = {"split": sp, "locked_params": p, "n_fit_rows": len(fit), "n_test_rows": len(hold),
               "n_patterns_passing": len(pats), "n_expected_by_construction": int(pats["expected_by_construction"].sum()),
               "n_topk_expected_by_construction": int(top["expected_by_construction"].sum()),
               "n_roadway_patterns": len(road_pats), "secondary_analyses": cfg.get("secondary_analyses"),
               "git_commit": info["git_commit"], "git_dirty": info["git_dirty"],
               "transactions_sha256": sha256_file(tx), "results": {}, "roadway_topk": {}}
    for key, lst in (("results", top), ("roadway_topk", road)):
        for kk in (k, k2):
            summary[key][f"top_{kk}"] = list_metrics(lst.head(kk), hold, ms, cfg, log, f"{key} K={kk}")

    # permutation null
    t0 = time.perf_counter()
    null = permutation_null(fit, hold, top, cfg, p, n_perm, cfg["seeds"]["permutation"], log)
    observed = {"n_patterns": len(pats), "max_lift": float(pats["fit_lift"].max()) if len(pats) else np.nan,
                "replication_rate": summary["results"][f"top_{k}"]["replication_rate"]}
    perm_rows = []
    for stat, obs in observed.items():
        col = null[stat].to_numpy(dtype=float)
        ge = int(np.sum(col >= obs)) if not np.isnan(obs) else 0
        perm_rows.append({"statistic": stat, "observed": obs, "null_mean": float(np.nanmean(col)) if len(col) else np.nan,
                          "null_p95": float(np.nanpercentile(col, 95)) if np.isfinite(col).any() else np.nan,
                          "null_percentile_of_observed": float(np.mean(col < obs) * 100) if len(col) else np.nan,
                          "count_null_ge_observed": ge, "n_resamples": n_perm, "p_value_one_sided": (ge + 1) / (n_perm + 1)})
    perm = pd.DataFrame(perm_rows)
    summary["permutation_null"] = {"n_resamples": n_perm, "seconds": round(time.perf_counter() - t0, 1),
                                   "statistics": perm.to_dict(orient="records")}
    log("permutation null (%d resamples, %.1f s):\n%s" % (n_perm, time.perf_counter() - t0,
                                                          perm.to_string(index=False, float_format="%.4f")))

    # stability by year and subgroups (county group, alcohol sensitivity), for both lists
    groups = pd.read_csv(companion(tx, "county"), dtype=str, keep_default_na=False)
    big = set(groups.loc[groups["group"] == "five most populous", "county_fips"])
    tables = {}
    for suffix, lst in (("", top), ("_roadway", road)):
        stab = stability(lst, df, sp, ms)
        county, county_summary, alc = subgroups(lst, hold, big, ms, cfg, log, suffix.strip("_") or "primary")
        tables[suffix] = (stab, county, alc)
        summary[f"subgroup_county{suffix}"] = county_summary
        summary[f"stability_share_present_all_fit_years{suffix}"] = (
            float(stab["present_in_all_fit_years"].mean()) if len(stab) else None)

    # unknown inflation by year
    unk_rows = []
    for var in cfg["item_variables"]:
        row = {"item": f"{var}={unknown}"}
        for y in sp["final_fit_years"] + [sp["test_year"]]:
            row[f"share_{y}"] = float((years(df, y)[var] == unknown).mean())
        row["share_fit_years"] = float((fit[var] == unknown).mean())
        row["share_test_minus_fit_pp"] = (row[f"share_{sp['test_year']}"] - row["share_fit_years"]) * 100
        unk_rows.append(row)
    unk = pd.DataFrame(unk_rows)

    # error analysis
    err = top.assign(abs_residual_candidate_pp=top["residual_candidate_pp"].abs())
    err = err.sort_values(["abs_residual_candidate_pp", "rank"], ascending=[False, True])
    err.insert(0, "worst_rank", range(1, len(err) + 1))
    err_cols = ["worst_rank", "rank", "itemset", "fit_support", "baseline_support", "obs_support", "obs_wilson_low",
                "obs_wilson_high", "residual_candidate_pp", "residual_baseline_pp", "replicated", "baseline_beats_candidate",
                "expected_by_construction", "hit_and_run_share_2024"]
    bvc = top[top["baseline_beats_candidate"]].assign(
        margin_pp=lambda d: d["residual_candidate_pp"].abs() - d["residual_baseline_pp"].abs())
    bvc = bvc.sort_values(["margin_pp", "rank"], ascending=[False, True])
    log("worst candidate residuals:\n" + err[err_cols[:3] + ["residual_candidate_pp", "residual_baseline_pp"]].head(5)
        .to_string(index=False, float_format="%.3f"))
    log(f"patterns where the baseline beats the candidate: {len(bvc)}")

    # write outputs (aggregates only: no case numbers, no person numbers, no coordinates)
    fmt = dict(index=False, float_format="%.6f", lineterminator="\n")
    for suffix, lst in (("", top), ("_roadway", road)):
        stab, county, alc = tables[suffix]
        lst.drop(columns=["items"]).to_csv(ev / f"patterns_topk{suffix}.csv", **fmt)
        (rules_table(lst, fit) if len(lst) else pd.DataFrame()).to_csv(ev / f"patterns_rules{suffix}.csv", **fmt)
        stab.to_csv(ev / f"stability_by_year{suffix}.csv", **fmt)
        county.to_csv(ev / f"subgroup_county{suffix}.csv", **fmt)
        alc.to_csv(ev / f"sensitivity_alcohol{suffix}.csv", **fmt)
    unk.to_csv(ev / "unknown_share_by_year.csv", **fmt)
    null.to_csv(ev / "permutation_null.csv", **fmt)
    perm.to_csv(ev / "permutation_summary.csv", **fmt)
    err[err_cols].to_csv(ev / "error_analysis.csv", **fmt)
    bvc[["rank", "itemset", "fit_support", "baseline_support", "obs_support", "residual_candidate_pp",
         "residual_baseline_pp", "margin_pp"]].to_csv(ev / "baseline_vs_candidate.csv", **fmt)
    summary["seconds"] = round(time.perf_counter() - t_start, 1)
    (ev / "results_summary.json").write_text(json.dumps(summary, indent=2, default=to_json) + "\n", encoding="utf-8")
    with open(ev / "test_runs.log", "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} | commit={info['git_commit']} "
                 f"dirty={info['git_dirty']} | forced={args.force or '-'} | completed in {summary['seconds']} s\n")
    log(f"test finished in {summary['seconds']} s; outputs in {ev}")
    return 0


def to_json(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    raise TypeError(type(v))


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["prepare", "tune", "test"])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--transactions", help="prepared CSV (default data/interim/experiment/transactions.csv)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="prepare: output directory when --transactions is not given")
    ap.add_argument("--evidence-dir", help="logs and outputs (default: config evidence_dir; test: docs/evidence/week11)")
    ap.add_argument("--locked", default=str(DEFAULT_LOCKED), help="locked parameters written by tune, read by test")
    ap.add_argument("--dsn", help="libpq connection string (default: PG* environment variables, database ped_safety)")
    ap.add_argument("--force", metavar="REASON", help="test: run again against the same evidence dir (reason is logged)")
    ap.add_argument("--permutations", type=int, help="override the number of permutation resamples (e.g. 50 in CI)")
    args = ap.parse_args(argv)
    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if args.evidence_dir is None:
        args.evidence_dir = str(ROOT / ("docs/evidence/week11" if args.stage == "test" else cfg["evidence_dir"]))
    if args.transactions is None and args.stage != "prepare":
        args.transactions = str(ROOT / cfg["outputs_dir"] / "transactions.csv")
    Path(args.evidence_dir).mkdir(parents=True, exist_ok=True)
    stage = {"prepare": stage_prepare, "tune": stage_tune, "test": stage_test}[args.stage]
    return stage(args, cfg, cfg_path)


if __name__ == "__main__":
    sys.exit(main())
