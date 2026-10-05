#!/usr/bin/env python3
"""
etl.py - Week 7 pipeline: raw FARS and Census files -> validated PostgreSQL tables.

One command loads everything, and running it again with the same files changes nothing:

    python pipeline/etl.py run                      # real files in data/raw/, pinned by pipeline/sources.csv
    python pipeline/etl.py stages                   # the stage list with dependencies and gates
    python pipeline/etl.py status [--run N]         # what a run did: steps, row counts, checks, errors
    python pipeline/etl.py rejected [--run N]       # records a run put in quarantine, and why
    python pipeline/etl.py snapshot                 # row counts and content fingerprints of the data tables

How a run is built (details in docs/Week7_Pipeline_Shkirpan.md):
  * Stages run in a fixed order; each one depends on the one before it. Six gates (G1-G6)
    stop the run when a check fails. Nothing is published until every gate has passed.
  * The publish is ONE transaction: the five years are deleted and inserted again, the
    post-load checks run inside the same transaction, and only then is it committed.
    A failure anywhere, or a killed process, leaves the tables exactly as they were.
  * Re-running with the same inputs replaces rows instead of adding them: the keys are
    composite (year, st_case, ...), and a year is deleted before it is inserted.
  * Bookkeeping (etl_run, etl_log, source_file, validation_result, rejected_record) is
    written on a second connection in autocommit mode, so the evidence of a failed run
    survives the rollback of its load.
  * One run at a time: a PostgreSQL advisory lock. A run that died without closing its
    etl_run row is closed as 'failed' by the next run, which then starts normally.

Connection settings come from the usual PostgreSQL environment variables (PGHOST, PGPORT,
PGUSER, PGDATABASE, default database ped_safety) or ~/.pgpass. Nothing is stored here.
The cleaning rules applied are the ones fixed in docs/Week6_Data_Cleaning_Plan_Shkirpan.md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd
import psycopg

try:                                    # pandera >= 0.24 moved the pandas API here
    import pandera.pandas as pa
except ImportError:                     # pragma: no cover - older pandera
    import pandera as pa

ROOT = Path(__file__).resolve().parents[1]
YEARS = [2020, 2021, 2022, 2023, 2024]
FL = 12
LOCK_KEY = 20262007                     # advisory lock id: one pipeline run at a time
DATA_TABLES = ["crash", "vehicle", "pedestrian", "ped_crash_type", "county_population"]
TABLE_KEYS = {
    "crash": "year, st_case",
    "vehicle": "year, st_case, veh_no",
    "pedestrian": "year, st_case, veh_no, per_no",
    "ped_crash_type": "year, st_case, veh_no, per_no",
    "county_population": "county_fips, year",
}

# Columns read from each FARS member (names as published, upper case).
REQUIRED = {
    "accident": ["STATE", "ST_CASE", "COUNTY", "MONTH", "DAY_WEEK", "HOUR", "RUR_URB", "FUNC_SYS",
                 "RELJCT2", "LGT_COND", "WEATHER", "LATITUDE", "LONGITUD", "TWAY_ID", "FATALS", "PEDS"],
    "vehicle":  ["STATE", "ST_CASE", "VEH_NO", "BODY_TYP", "VSPD_LIM", "HIT_RUN"],
    "person":   ["STATE", "ST_CASE", "VEH_NO", "PER_NO", "PER_TYP", "INJ_SEV", "AGE", "SEX", "DRINKING", "STR_VEH"],
    "pbtype":   ["STATE", "ST_CASE", "VEH_NO", "PER_NO", "PBCWALK", "PBSWALK", "PEDLOC", "PEDPOS", "PEDCTYPE"],
}
CENSUS_REQUIRED = ["SUMLEV", "STATE", "COUNTY", "CTYNAME"] + [f"POPESTIMATE{y}" for y in YEARS]
RAW_KEYS = {"accident": ["ST_CASE"], "vehicle": ["ST_CASE", "VEH_NO"],
            "person": ["ST_CASE", "VEH_NO", "PER_NO"], "pbtype": ["ST_CASE", "VEH_NO", "PER_NO"]}

# Target columns of the core tables, in load order.
COLS = {
    "crash": ["year", "st_case", "county", "month", "day_week", "hour", "rur_urb", "func_sys", "reljct2",
              "lgt_cond", "weather", "latitude", "longitud", "geoid10", "tway_id", "fatals", "peds"],
    "vehicle": ["year", "st_case", "veh_no", "body_typ", "vspd_lim", "hit_run"],
    "pedestrian": ["year", "st_case", "veh_no", "per_no", "str_veh", "per_typ", "inj_sev", "age", "sex", "drinking"],
    "ped_crash_type": ["year", "st_case", "veh_no", "per_no", "pbcwalk", "pbswalk", "pedloc", "pedpos", "pedctype"],
    "county_population": ["county_fips", "year", "population", "vintage"],
}
SOURCE_MEMBER = {"crash": "accident", "vehicle": "vehicle", "pedestrian": "person", "ped_crash_type": "pbtype"}
# Variables whose allowed codes are read from code_lookup, per year (cleaning plan, issue 4).
LOOKUP_VARS = {
    "crash": ["day_week", "rur_urb", "func_sys", "reljct2", "lgt_cond", "weather"],
    "vehicle": ["hit_run"],
    "pedestrian": ["per_typ", "inj_sev", "sex", "drinking"],
    "ped_crash_type": ["pbcwalk", "pbswalk", "pedloc", "pedpos"],
}
LAT_FILLERS = {77.7777, 88.8888, 99.9999}
LON_FILLERS = {777.7777, 888.8888, 999.9999}


class GateFailed(Exception):
    """A validation gate refused the data. The run stops; nothing is published."""


# ---------------------------------------------------------------------------
# Logging: every line carries a timestamp with offset, the run id and the stage.
# Lines go to the console and to logs/run_<id>.log; the important ones also go
# to etl_log, so a run can be diagnosed from the database alone.
# ---------------------------------------------------------------------------
class RunLog:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.run_id: int | None = None
        self.stage = "-"
        self.buffer: list[str] = []
        self.fh = None
        self.path: Path | None = None
        self.bk = None                       # bookkeeping connection, set after preflight
        self.redact = False                  # --redact-keys: mask case numbers in every log line

    def line(self, level: str, msg: str, rows_in=None, rows_out=None) -> None:
        ts = datetime.now().astimezone().isoformat(timespec="milliseconds")
        counts = ""
        if rows_in is not None:
            counts += f" rows_in={rows_in}"
        if rows_out is not None:
            counts += f" rows_out={rows_out}"
        text = f"{ts} run={self.run_id if self.run_id else '-'} stage={self.stage} {level}{counts} | {msg}"
        if self.redact:
            text = re.sub(r"\b12\d{4}\b", "12xxxx", text)
        print(text, flush=True)
        if self.fh:
            self.fh.write(text + "\n")
            self.fh.flush()
        else:
            self.buffer.append(text)

    def info(self, msg, **kw):
        self.line("INFO", msg, **kw)

    def warn(self, msg, **kw):
        self.line("WARN", msg, **kw)

    def error(self, msg, **kw):
        self.line("ERROR", msg, **kw)

    def attach(self, run_id: int) -> None:
        self.run_id = run_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # run ids restart after a database rebuild, so the start time keeps the file names unique
        self.path = self.log_dir / f"run_{run_id:04d}_{datetime.now():%Y%m%dT%H%M%S}.log"
        self.fh = open(self.path, "w", encoding="utf-8")
        for text in self.buffer:
            self.fh.write(text.replace(" run=- ", f" run={run_id} ", 1) + "\n")
        self.fh.flush()
        self.buffer = []

    def step(self, message: str, status: str = "ok", rows_in=None, rows_out=None, step: str | None = None) -> None:
        """Text log line plus one etl_log row."""
        {"ok": self.info, "warning": self.warn, "error": self.error}[status](message, rows_in=rows_in, rows_out=rows_out)
        if self.bk is not None and self.run_id is not None:
            self.bk.execute(
                "INSERT INTO etl_log (run_id, step, rows_in, rows_out, status, message) VALUES (%s, %s, %s, %s, %s, %s)",
                (self.run_id, step or self.stage, rows_in, rows_out, status, message))


@dataclass
class Ctx:
    args: argparse.Namespace
    log: RunLog
    bk: psycopg.Connection | None = None             # autocommit: bookkeeping
    db: psycopg.Connection | None = None             # one transaction: the load
    run_id: int | None = None
    sources: list[dict] = field(default_factory=list)
    expected: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)          # raw[year][member] -> Florida rows (str)
    national: dict = field(default_factory=dict)     # national[(year, member)] -> row count
    census: pd.DataFrame | None = None
    unit: dict = field(default_factory=dict)         # unit[table] -> typed frame, all years
    fingerprint_before: str = ""
    committed: bool = False                          # the load transaction (with status 'succeeded') is committed
    checks_failed: list[str] = field(default_factory=list)


@dataclass
class Stage:
    name: str
    deps: list[str]
    gate: str
    doc: str
    fn: Callable[[Ctx], str | None]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decode(raw: bytes, encodings: tuple[str, ...]) -> tuple[str, str]:
    for enc in encodings:
        try:
            return raw.decode(enc).lstrip("\ufeff"), enc         # a byte-order mark would hide the first column name
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot be decoded as {' or '.join(encodings)}")


def read_member(text: str, required: list[str]) -> tuple[pd.DataFrame | None, list[str], int]:
    """Read a CSV as text (nothing coerced). Returns (frame of the required columns, missing columns, rows)."""
    header = next(csv.reader(io.StringIO(text.split("\n", 1)[0])))
    names = [h.strip().upper() for h in header]
    missing = [c for c in required if c not in names]
    if missing:
        return None, missing, 0
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, header=0, names=names,
                     usecols=lambda c: c in required, index_col=False, low_memory=False)
    df = df.apply(lambda s: s.str.strip())
    df["_line"] = df.index + 2                      # line number in the CSV (line 1 = header)
    return df[required + ["_line"]], [], len(df)


def to_int(s: pd.Series) -> pd.Series:
    """Text -> nullable integer. Anything that is not a whole number becomes NA (and fails a gate)."""
    n = pd.to_numeric(s, errors="coerce")
    return n.where(n == n.round()).astype("Int64")


def find_member(zf: zipfile.ZipFile, name: str) -> str | None:
    for m in zf.namelist():
        if Path(m).name.lower() == f"{name}.csv":
            return m
    return None


def fingerprint(conn) -> tuple[dict, str]:
    """Row count and md5 of every data table's content, plus one combined hash."""
    out = {}
    for t in DATA_TABLES:
        n, h = conn.execute(f"SELECT count(*), coalesce(md5(string_agg(t::text, '|' ORDER BY t::text)), '-') FROM {t} t").fetchone()
        out[t] = (n, h)
    combined = hashlib.md5("".join(h for _, h in out.values()).encode()).hexdigest()
    return out, combined


def git_commit() -> tuple[str | None, bool]:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", ".", ":!docs/evidence"], cwd=ROOT,
                                    capture_output=True, text=True).stdout.strip())
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False


def conninfo(args) -> str:
    if args.dsn:
        return args.dsn
    return "" if os.environ.get("PGDATABASE") else "dbname=ped_safety"


def check(ctx: Ctx, name: str, passed: bool, detail: str, blocking: bool = True) -> bool:
    """One validation_result row and one log line per check."""
    if not blocking:
        name += " (warning only)"
    ctx.bk.execute("INSERT INTO validation_result (run_id, check_name, passed, detail) VALUES (%s, %s, %s, %s)",
                   (ctx.run_id, name, passed, detail))
    if passed:
        ctx.log.info(f"PASS  {name}: {detail}")
    elif blocking:
        ctx.log.error(f"FAIL  {name}: {detail}")
        ctx.checks_failed.append(name)
    else:
        ctx.log.warn(f"WARN  {name}: {detail}")
    return passed


def gate(ctx: Ctx, label: str) -> None:
    if ctx.checks_failed:
        failed, ctx.checks_failed = ctx.checks_failed, []
        raise GateFailed(f"{label}: {len(failed)} blocking check(s) failed: " + "; ".join(failed[:6])
                         + (" ..." if len(failed) > 6 else ""))


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def s_preflight(ctx: Ctx) -> None:
    ctx.bk = psycopg.connect(conninfo(ctx.args), autocommit=True)
    if not ctx.bk.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
        raise SystemExit(ctx.log.error("another pipeline run holds the lock; wait for it to finish") or 3)
    missing = [t for t in ["etl_run", "rejected_record", "crash", "code_lookup"]
               if ctx.bk.execute("SELECT to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is None]
    if missing:
        raise SystemExit(ctx.log.error(f"database is not built for Week 7 (missing {missing}); "
                                       "run: psql -d ped_safety -v ON_ERROR_STOP=1 -f sql/00_build_all.sql") or 2)
    sha, dirty = git_commit()
    ctx.run_id, started = ctx.bk.execute(
        "INSERT INTO etl_run (git_commit, status) VALUES (%s, 'running') RETURNING run_id, started_at", (sha,)).fetchone()
    ctx.log.attach(ctx.run_id)
    ctx.log.bk = ctx.bk
    # This run holds the lock, so any other 'running' row belongs to a process that died. A run only
    # becomes 'succeeded' inside its load transaction (s_verify_load), so a 'running' row never committed data.
    abandoned = ctx.bk.execute(
        "UPDATE etl_run SET status = 'failed', finished_at = greatest(now(), started_at) "
        "WHERE status = 'running' AND run_id <> %s RETURNING run_id, started_at", (ctx.run_id,)).fetchall()
    for old_id, old_start in abandoned:
        ctx.bk.execute("INSERT INTO etl_log (run_id, step, status, message) VALUES (%s, 'recovery', 'error', %s)",
                       (old_id, f"abandoned: the process ended without closing the run; closed by run {ctx.run_id}"))
        ctx.log.step(f"recovered abandoned run {old_id} (started {old_start.astimezone().isoformat(timespec='seconds')}): status set to failed; "
                     "its load transaction was never committed, so no rows of it exist", status="warning")
    ctx.log.step(f"run {ctx.run_id} started {started.astimezone().isoformat(timespec='seconds')}; git commit {sha or 'unknown'}"
                 + (" (working tree has uncommitted changes)" if dirty else ""))
    ctx.log.step(f"inputs: raw dir {ctx.args.raw_dir}; sources {ctx.args.sources}; expected counts {ctx.args.expected}")
    counts, ctx.fingerprint_before = fingerprint(ctx.bk)
    ctx.log.step("data tables before the run: " + ", ".join(f"{t}={n}" for t, (n, _) in counts.items())
                 + f"; fingerprint {ctx.fingerprint_before[:12]}")


def s_verify_sources(ctx: Ctx) -> None:
    with open(ctx.args.sources, newline="", encoding="utf-8") as f:
        ctx.sources = list(csv.DictReader(f))
    fars_years = sorted(int(s["data_year"]) for s in ctx.sources if s["source"] == "FARS")
    check(ctx, "G1 sources.csv lists FARS 2020-2024 and the Census file",
          fars_years == YEARS and any(s["source"] == "CENSUS_POPEST" for s in ctx.sources),
          f"FARS years {fars_years}; census {'yes' if any(s['source'] == 'CENSUS_POPEST' for s in ctx.sources) else 'no'}")
    for s in ctx.sources:
        path = Path(ctx.args.raw_dir) / s["file_name"]
        if not path.exists():
            check(ctx, f"G1 sha256 {s['file_name']}", False, f"file not found: {path}")
            continue
        size, actual = path.stat().st_size, sha256(path)
        ok = actual == s["sha256"] and size == int(s["bytes"])
        check(ctx, f"G1 sha256 {s['file_name']}", ok,
              f"expected {s['sha256'][:16]}... ({int(s['bytes']):,} bytes), found {actual[:16]}... ({size:,} bytes)")
    gate(ctx, "G1 integrity")
    for s in ctx.sources:
        ctx.bk.execute(
            "INSERT INTO source_file (run_id, source, data_year, release, file_name, url, sha256, retrieved_on) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (ctx.run_id, s["source"], int(s["data_year"]) if s["data_year"] else None, s["release"],
             s["file_name"], s["url"], s["sha256"], s["retrieved_on"]))
    ctx.log.step(f"{len(ctx.sources)} input files verified against sources.csv and recorded in source_file",
                 rows_in=len(ctx.sources), rows_out=len(ctx.sources))


def s_extract(ctx: Ctx) -> None:
    raw_dir = Path(ctx.args.raw_dir)
    for s in [s for s in ctx.sources if s["source"] == "FARS"]:
        year = int(s["data_year"])
        ctx.raw[year] = {}
        with zipfile.ZipFile(raw_dir / s["file_name"]) as zf:
            for member, required in REQUIRED.items():
                name = find_member(zf, member)
                if name is None:
                    check(ctx, f"G2 {year} {member}.csv present", False, f"no {member}.csv in {s['file_name']}")
                    continue
                try:
                    text, enc = decode(zf.read(name), ("utf-8", "cp1252"))
                    df, missing, n = read_member(text, required)
                except Exception as e:  # noqa: BLE001 - any unreadable member is a structure failure
                    check(ctx, f"G2 {year} {member}.csv readable", False, f"{s['file_name']}:{name}: {type(e).__name__}: {e}")
                    continue
                if not check(ctx, f"G2 {year} {member}.csv required columns", not missing,
                             f"missing {missing}" if missing else f"{len(required)} columns present ({enc})"):
                    continue
                fl = df[to_int(df["STATE"]) == FL].copy()
                ctx.raw[year][member] = fl
                ctx.national[(year, member)] = n
                ctx.log.step(f"{year} {member}.csv: kept STATE = 12 (encoding {enc})", rows_in=n, rows_out=len(fl))
    census = next(s for s in ctx.sources if s["source"] == "CENSUS_POPEST")
    try:
        text, enc = decode((raw_dir / census["file_name"]).read_bytes(), ("utf-8", "latin-1"))
        df, missing, n = read_member(text, CENSUS_REQUIRED)
    except Exception as e:  # noqa: BLE001
        check(ctx, "G2 census readable", False, f"{census['file_name']}: {type(e).__name__}: {e}")
        gate(ctx, "G2 structure")
    if check(ctx, "G2 census required columns", not missing,
             f"missing {missing}" if missing else f"{len(CENSUS_REQUIRED)} columns present ({enc})"):
        ctx.census = df[(to_int(df["SUMLEV"]) == 50) & (to_int(df["STATE"]) == FL)].copy()
        ctx.log.step(f"census: kept SUMLEV 050 and STATE 12 (encoding {enc}; the state summary row is dropped)",
                     rows_in=n, rows_out=len(ctx.census))
    gate(ctx, "G2 structure")


def s_reconcile_inventory(ctx: Ctx) -> None:
    # The reconciliation totals are required: a missing or incomplete file fails the gate, it never switches it off.
    try:
        ctx.expected = read_expected(Path(ctx.args.expected))
        missing = [f"{y} {m}" for y in YEARS for m in [f"{x}_fl_rows" for x in REQUIRED] + ["ped_fatalities", "crashes_with_ped_fatality"]
                   if ("FARS", y, m) not in ctx.expected]
        missing += ["census fl_county_rows"] if ("CENSUS_POPEST", None, "fl_county_rows") not in ctx.expected else []
        check(ctx, "G3 expected_counts.csv present and complete", not missing,
              f"{len(ctx.expected)} totals read from {ctx.args.expected}" if not missing else f"missing: {', '.join(missing[:8])}")
    except Exception as e:  # noqa: BLE001
        check(ctx, "G3 expected_counts.csv present and complete", False, f"{ctx.args.expected}: {type(e).__name__}: {e}")
    gate(ctx, "G3 inventory reconciliation")
    for year in YEARS:
        for member in REQUIRED:
            exp = ctx.expected[("FARS", year, f"{member}_fl_rows")]
            got = len(ctx.raw[year][member])
            check(ctx, f"G3 {year} {member} Florida rows", got == exp, f"expected {exp:,}, read {got:,}")
    exp = ctx.expected[("CENSUS_POPEST", None, "fl_county_rows")]
    check(ctx, "G3 census Florida county rows", len(ctx.census) == exp, f"expected {exp}, read {len(ctx.census)}")
    gate(ctx, "G3 inventory reconciliation")


def s_transform(ctx: Ctx) -> None:
    frames = {t: [] for t in ["crash", "vehicle", "pedestrian", "ped_crash_type"]}
    tot = dict(fill=0, sv0=0, svx=0)
    for year in YEARS:
        acc, veh, per, pbt = (ctx.raw[year][m] for m in ["accident", "vehicle", "person", "pbtype"])
        # unit of observation: one pedestrian fatality (PER_TYP 5, INJ_SEV 4)
        is_ped = (to_int(per["PER_TYP"]) == 5) & (to_int(per["INJ_SEV"]) == 4)
        p = pd.DataFrame({"year": year, "st_case": to_int(per["ST_CASE"]), "veh_no": to_int(per["VEH_NO"]),
                          "per_no": to_int(per["PER_NO"]), "str_veh": to_int(per["STR_VEH"]),
                          "per_typ": to_int(per["PER_TYP"]), "inj_sev": to_int(per["INJ_SEV"]),
                          "age": to_int(per["AGE"]), "sex": to_int(per["SEX"]), "drinking": to_int(per["DRINKING"]),
                          "_line": per["_line"]})[is_ped.fillna(False).to_numpy()]
        ctx.log.step(f"{year} person -> pedestrian: PER_TYP = 5 and INJ_SEV = 4", rows_in=len(per), rows_out=len(p))
        cases = set(p["st_case"].dropna())
        a = acc[to_int(acc["ST_CASE"]).isin(cases).fillna(False).to_numpy()]
        lat = pd.to_numeric(a["LATITUDE"], errors="coerce")
        lon = pd.to_numeric(a["LONGITUD"], errors="coerce")
        filler = lat.round(4).isin(LAT_FILLERS) | lon.round(4).isin(LON_FILLERS)
        c = pd.DataFrame({"year": year, "st_case": to_int(a["ST_CASE"]), "county": to_int(a["COUNTY"]),
                          "month": to_int(a["MONTH"]), "day_week": to_int(a["DAY_WEEK"]), "hour": to_int(a["HOUR"]),
                          "rur_urb": to_int(a["RUR_URB"]), "func_sys": to_int(a["FUNC_SYS"]),
                          "reljct2": to_int(a["RELJCT2"]), "lgt_cond": to_int(a["LGT_COND"]),
                          "weather": to_int(a["WEATHER"]),
                          "latitude": lat.where(~filler).astype("Float64"), "longitud": lon.where(~filler).astype("Float64"),
                          "geoid10": None, "tway_id": a["TWAY_ID"].where(a["TWAY_ID"] != "", None),
                          "fatals": to_int(a["FATALS"]), "peds": to_int(a["PEDS"]), "_line": a["_line"]})
        tot["fill"] += int(filler.sum())
        ctx.log.step(f"{year} accident -> crash: crashes with at least one pedestrian fatality; "
                     f"{int(filler.sum())} filler coordinate pair(s) (77.7777 / 88.8888 / 99.9999) set to NULL",
                     rows_in=len(acc), rows_out=len(c))
        v = veh[to_int(veh["ST_CASE"]).isin(set(c["st_case"].dropna())).fillna(False).to_numpy()]
        v = pd.DataFrame({"year": year, "st_case": to_int(v["ST_CASE"]), "veh_no": to_int(v["VEH_NO"]),
                          "body_typ": to_int(v["BODY_TYP"]), "vspd_lim": to_int(v["VSPD_LIM"]),
                          "hit_run": to_int(v["HIT_RUN"]), "_line": v["_line"]})
        ctx.log.step(f"{year} vehicle -> vehicle: in-transport vehicles of those crashes", rows_in=len(veh), rows_out=len(v))
        # business rule 2: STR_VEH 0, or a number with no vehicle in the same crash, becomes NULL
        sv0 = p["str_veh"] == 0
        vkeys = set(zip(v["st_case"], v["veh_no"]))
        unresolved = ~sv0 & ~pd.Series([(s, x) in vkeys for s, x in zip(p["st_case"], p["str_veh"])], index=p.index)
        p.loc[(sv0 | unresolved).fillna(False), "str_veh"] = pd.NA
        tot["sv0"] += int(sv0.sum())
        tot["svx"] += int(unresolved.sum())
        if int(sv0.sum()) or int(unresolved.sum()):
            ctx.log.step(f"{year} STR_VEH: {int(sv0.sum())} coded 0 and {int(unresolved.sum())} without a vehicle in the "
                         "same crash set to NULL (rule 2; the death is kept)", status="warning")
        pkeys = set(zip(p["st_case"], p["veh_no"], p["per_no"]))
        sel = [(s, x, n) in pkeys for s, x, n in zip(to_int(pbt["ST_CASE"]), to_int(pbt["VEH_NO"]), to_int(pbt["PER_NO"]))]
        b = pbt[sel]
        t = pd.DataFrame({"year": year, "st_case": to_int(b["ST_CASE"]), "veh_no": to_int(b["VEH_NO"]),
                          "per_no": to_int(b["PER_NO"]), "pbcwalk": to_int(b["PBCWALK"]), "pbswalk": to_int(b["PBSWALK"]),
                          "pedloc": to_int(b["PEDLOC"]), "pedpos": to_int(b["PEDPOS"]),
                          "pedctype": to_int(b["PEDCTYPE"]), "_line": b["_line"]})
        ctx.log.step(f"{year} pbtype -> ped_crash_type: typing records of the pedestrian fatalities",
                     rows_in=len(pbt), rows_out=len(t))
        for name, df in [("crash", c), ("vehicle", v), ("pedestrian", p), ("ped_crash_type", t)]:
            frames[name].append(df)
    for name, parts in frames.items():
        ctx.unit[name] = pd.concat(parts, ignore_index=True)
        ctx.unit[name]["year"] = ctx.unit[name]["year"].astype("Int64")
    cen = ctx.census
    long = []
    vintage = int("".join(ch for ch in next(s for s in ctx.sources if s["source"] == "CENSUS_POPEST")["release"] if ch.isdigit()) or 2025)
    for y in YEARS:
        long.append(pd.DataFrame({"county_fips": to_int(cen["COUNTY"]), "year": y,
                                  "population": to_int(cen[f"POPESTIMATE{y}"]), "vintage": vintage, "_line": cen["_line"]}))
    ctx.unit["county_population"] = pd.concat(long, ignore_index=True)
    ctx.unit["county_population"]["year"] = ctx.unit["county_population"]["year"].astype("Int64")
    ctx.log.step(f"census -> county_population: one row per county and year (vintage {vintage})",
                 rows_in=len(cen), rows_out=len(ctx.unit["county_population"]))
    ctx.log.step("unit totals: " + ", ".join(f"{k}={len(v):,}" for k, v in ctx.unit.items()))


def s_join_block_groups(ctx: Ctx) -> str:
    n = len(ctx.unit["crash"])
    ctx.log.step(f"skipped: the EPA Smart Location Database is not in sources.csv yet, so crash.geoid10 stays NULL "
                 f"for all {n:,} crashes and the walkability item reads 'unknown' (cleaning plan, issue 5)",
                 status="warning", rows_in=n, rows_out=0)
    return "skipped"


def _pa_int(checks=None, nullable=False):
    return pa.Column("Int64", checks=checks or [], nullable=nullable, coerce=False)


def _codes(lookup: dict, var: str, year: int) -> list[int]:
    return sorted(c for (v, c, y0, y1) in lookup if v == var and y0 <= year <= y1)


def unit_schema(table: str, year: int | None, ref: dict) -> pa.DataFrameSchema:
    """Record-level rules: the schema CHECKs, code lists valid for the year, and reference tables."""
    rng = lambda lo, hi, extra=(), nm="": pa.Check(lambda s: s.between(lo, hi) | s.isin(list(extra)),
                                                   name=nm or f"in {lo}-{hi}" + (f" or {list(extra)}" if extra else ""))
    cols: dict[str, pa.Column] = {"year": _pa_int([pa.Check.isin(YEARS, error="2020-2024")])}
    if table != "county_population":
        cols["st_case"] = _pa_int([rng(120001, 129999, nm="Florida case number 120001-129999")])
    if table == "crash":
        cols["st_case"] = _pa_int([rng(120001, 129999, nm="Florida case number 120001-129999"),
                                   pa.Check.isin(ref["veh_cases"], error="crash has at least one in-transport vehicle")])
        cols.update(county=_pa_int([pa.Check.isin(ref["county"], error="one of the 67 Florida counties")]),
                    month=_pa_int([rng(1, 12)]), hour=_pa_int([rng(0, 23, [99])]),
                    latitude=pa.Column("Float64", [pa.Check.in_range(24.3, 31.1, error="inside the Florida box")], nullable=True),
                    longitud=pa.Column("Float64", [pa.Check.in_range(-87.7, -79.8, error="inside the Florida box")], nullable=True),
                    fatals=_pa_int([rng(1, 99)]), peds=_pa_int([rng(1, 99)]))
    if table == "vehicle":
        cols.update(veh_no=_pa_int([rng(1, 999)]), body_typ=_pa_int([rng(1, 99)]), vspd_lim=_pa_int([rng(0, 95, [98, 99])]))
    if table == "pedestrian":
        cols.update(veh_no=_pa_int([pa.Check.isin([0], error="0 for people outside vehicles")]), per_no=_pa_int([rng(1, 999)]),
                    str_veh=_pa_int([rng(1, 999)], nullable=True), age=_pa_int([rng(0, 120, [998, 999])]))
    if table == "ped_crash_type":
        cols.update(veh_no=_pa_int([pa.Check.isin([0], error="0 for people outside vehicles")]), per_no=_pa_int([rng(1, 999)]),
                    pedctype=_pa_int([pa.Check.isin(ref["pedctype"], error="a PBCAT type in pbcat_type")]))
    if table == "county_population":
        cols.update(county_fips=_pa_int([pa.Check.isin(ref["county"], error="one of the 67 Florida counties")]),
                    population=_pa_int([pa.Check.gt(0, error="greater than 0")]))
        return pa.DataFrameSchema(cols, unique=["county_fips", "year"], report_duplicates="exclude_first", strict=False)
    for var in LOOKUP_VARS.get(table, []):
        cols[var] = _pa_int([pa.Check.isin(_codes(ref["lookup"], var, year), error=f"code with a {year} label in code_lookup")])
    return pa.DataFrameSchema(cols, strict=False)


def person_key(raw: pd.DataFrame) -> pd.Series:
    return to_int(raw["ST_CASE"]).astype(str) + "/" + to_int(raw["VEH_NO"]).astype(str) + "/" + to_int(raw["PER_NO"]).astype(str)


FLOAT_COLS = {"LATITUDE", "LONGITUD"}
TEXT_COLS = {"STATE", "TWAY_ID"}


def raw_typed(member: str, raw: pd.DataFrame) -> pd.DataFrame:
    """The raw Florida rows with every coded column converted; a blank or non-numeric cell becomes NA."""
    typed = pd.DataFrame({c: pd.to_numeric(raw[c], errors="coerce").astype("Float64") if c in FLOAT_COLS else to_int(raw[c])
                          for c in REQUIRED[member] if c not in TEXT_COLS})
    if member == "pbtype":
        typed["_PERSON_KEY"] = person_key(raw)
    typed["_line"] = raw["_line"]
    return typed


def raw_schema(member: str, accident_cases: list, person_keys: list) -> pa.DataFrameSchema:
    """Raw-file rules (cleaning plan, issue 3): every coded cell is a number, unique keys within the year,
    no orphan rows. They run on all Florida rows, so a blank PER_TYP cannot silently drop a death later."""
    cols = {c: pa.Column("Float64" if c in FLOAT_COLS else "Int64", nullable=False)
            for c in REQUIRED[member] if c not in TEXT_COLS}
    if member != "accident":
        cols["ST_CASE"] = pa.Column("Int64", [pa.Check.isin(accident_cases, error="ST_CASE exists in accident.csv (no orphan)")])
    if member == "pbtype":
        cols["_PERSON_KEY"] = pa.Column(str, [pa.Check.isin(person_keys, error="matching row exists in person.csv (no orphan typing record)")])
    return pa.DataFrameSchema(cols, unique=RAW_KEYS[member], report_duplicates="exclude_first", strict=False)


def _failures(err: pa.errors.SchemaErrors) -> list[tuple[int, str, str | None, str]]:
    out = []
    for _, r in err.failure_cases.iterrows():
        col = r["column"] if isinstance(r["column"], str) else None
        if pd.isna(r["index"]):              # a whole-column problem (wrong type, missing column): no row to quarantine
            out.append((None, str(r["check"]), col, None if pd.isna(r["failure_case"]) else str(r["failure_case"])))
            continue
        name = str(r["check"])
        if name == "not_nullable":
            name = "blank or not a number"
        elif "uniqueness" in name or name.startswith("field_uniqueness"):
            name = "duplicate key within the year"
            col = None
        out.append((int(r["index"]), name, col, None if pd.isna(r["failure_case"]) else str(r["failure_case"])))
    return out


def s_validate_records(ctx: Ctx) -> None:
    ref = {"county": [r[0] for r in ctx.bk.execute("SELECT county_fips FROM county")],
           "pedctype": [r[0] for r in ctx.bk.execute("SELECT pedctype FROM pbcat_type")],
           "lookup": ctx.bk.execute("SELECT variable, code, year_from, year_to FROM code_lookup").fetchall()}
    file_of = {int(s["data_year"]): s["file_name"] for s in ctx.sources if s["source"] == "FARS"}
    census_file = next(s for s in ctx.sources if s["source"] == "CENSUS_POPEST")["file_name"]
    rejects: list[dict] = []
    per_table: dict[str, list[str]] = {}

    def collect(layer, target, year, file_name, member, df, raw_df, schema, key_cols):
        try:
            schema.validate(df, lazy=True)
            return
        except pa.errors.SchemaErrors as err:
            seen = set()
            for idx, name, col, val in _failures(err):
                if (idx, name, col) in seen:
                    continue
                seen.add((idx, name, col))
                if idx is None:
                    per_table.setdefault((layer, target), []).append(f"{year or ''} whole column {col}: {name} {val or ''}")
                    continue
                row = df.loc[idx]
                line = int(row["_line"]) if "_line" in row and pd.notna(row["_line"]) else None
                match = raw_df[raw_df["_line"] == line] if line else raw_df.iloc[0:0]
                rawrow = match.drop(columns="_line").iloc[0].to_dict() if len(match) else {}
                if val is None and col:                  # a blank or non-numeric cell: show the text as read
                    val = rawrow.get(col.upper(), rawrow.get(col))
                rejects.append(dict(year=year, file_name=file_name, member=member, line=line, target=target,
                                    key="/".join(str(df.at[idx, k]) for k in key_cols if k in df.columns), check=name, column=col,
                                    value=val, raw=rawrow))
                per_table.setdefault((layer, target), []).append(f"{year or ''} {col or ''}: {name}".strip())

    for year in YEARS:
        acc_cases = to_int(ctx.raw[year]["accident"]["ST_CASE"]).dropna().tolist()
        per = ctx.raw[year]["person"]
        person_keys = person_key(per).tolist()
        for member in REQUIRED:
            raw = ctx.raw[year][member]
            collect("raw file", member, year, file_of[year], f"{member}.csv", raw_typed(member, raw), raw,
                    raw_schema(member, acc_cases, person_keys), RAW_KEYS[member])
        ref["veh_cases"] = ctx.unit["vehicle"].loc[ctx.unit["vehicle"]["year"] == year, "st_case"].dropna().unique().tolist()
        for table in ["crash", "vehicle", "pedestrian", "ped_crash_type"]:
            df = ctx.unit[table]
            df = df[df["year"] == year]
            member = SOURCE_MEMBER[table]
            collect("record rules", table, year, file_of[year], f"{member}.csv", df, ctx.raw[year][member],
                    unit_schema(table, year, ref), TABLE_KEYS[table].split(", "))
    collect("record rules", "county_population", None, census_file, census_file, ctx.unit["county_population"],
            ctx.census, unit_schema("county_population", None, ref), ["county_fips", "year"])

    for r in rejects:
        ctx.bk.execute(
            "INSERT INTO rejected_record (run_id, data_year, file_name, member, source_line, target_table, record_key, "
            "check_name, column_name, failure_value, raw_record) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (ctx.run_id, r["year"], r["file_name"], r["member"], r["line"], r["target"], r["key"], r["check"],
             r["column"], r["value"], json.dumps(r["raw"])))
        if ctx.args.redact_keys:                     # real data: no key, line or value in the published log
            ctx.log.error(f"REJECT {r['target']} ({r['file_name']}:{r['member']}): {r['check']}"
                          + (f" [{r['column']}]" if r["column"] else ""))
        else:
            ctx.log.error(f"REJECT {r['target']} {r['key']} ({r['file_name']}:{r['member']} line {r['line']}): "
                          f"{r['check']}" + (f" [{r['column']}={r['value']}]" if r["column"] else ""))
    records = len({(r["file_name"], r["member"], r["line"], r["target"]) for r in rejects})
    rows_checked = sum(len(ctx.raw[y][m]) for y in YEARS for m in REQUIRED) + sum(len(d) for d in ctx.unit.values())
    for layer, targets in [("raw file", list(REQUIRED)),
                           ("record rules", ["crash", "vehicle", "pedestrian", "ped_crash_type", "county_population"])]:
        for target in targets:
            bad = per_table.get((layer, target), [])
            check(ctx, f"G4 {layer} {target}", not bad,
                  "0 failures" if not bad else f"{len(bad)} failure(s): " + "; ".join(sorted(set(bad)))[:400])
    ctx.log.step(f"record-level rules applied to {rows_checked:,} rows; {records} record(s) rejected "
                 f"({len(rejects)} rule failure(s)) into rejected_record",
                 status="ok" if not rejects else "error", rows_in=rows_checked, rows_out=rows_checked - records)
    gate(ctx, f"G4 record rules ({records} record(s) in rejected_record, run {ctx.run_id})")


def s_reconcile_unit(ctx: Ctx) -> None:
    for year in YEARS:
        for measure, table, fn in [("ped_fatalities", "pedestrian", len),
                                   ("crashes_with_ped_fatality", "crash", len)]:
            exp = ctx.expected[("FARS", year, measure)]
            got = int((ctx.unit[table]["year"] == year).sum())
            check(ctx, f"G5 {year} {measure}", got == exp, f"expected (Week 6 profile / published) {exp:,}, derived {got:,}")
    gate(ctx, "G5 unit reconciliation")


def _rows(df: pd.DataFrame, cols: list[str]):
    out = df[cols].astype(object)
    return out.where(out.notna(), None).itertuples(index=False, name=None)


def s_load(ctx: Ctx) -> None:
    ctx.db = psycopg.connect(conninfo(ctx.args))          # autocommit off: everything below is one transaction
    cur = ctx.db.cursor()
    before = {t: dict(cur.execute(f"SELECT year, count(*) FROM {t} GROUP BY year").fetchall()) for t in DATA_TABLES}
    cur.execute("DELETE FROM crash WHERE year = ANY(%s)", (YEARS,))          # cascades to vehicle, pedestrian, ped_crash_type
    cur.execute("DELETE FROM county_population WHERE year = ANY(%s)", (YEARS,))
    for table in DATA_TABLES:
        df = ctx.unit[table]
        with cur.copy(f"COPY {table} ({', '.join(COLS[table])}) FROM STDIN") as cp:
            for row in _rows(df, COLS[table]):
                cp.write_row(row)
        for year in YEARS:
            n_new = int((df["year"] == year).sum())
            ctx.log.step(f"{year} {table}: deleted {before[table].get(year, 0):,} row(s) of the previous load, "
                         f"inserted {n_new:,}", rows_in=before[table].get(year, 0), rows_out=n_new, step="load")
    cur.execute("SET CONSTRAINTS ALL IMMEDIATE")            # the deferred 'one or more' triggers run here
    ctx.log.step("deferred cardinality triggers passed (every crash has a pedestrian and a vehicle); "
                 "transaction still open")


def s_verify_load(ctx: Ctx) -> None:
    q = lambda sql, *a: ctx.db.execute(sql, a or None).fetchone()[0]
    for table in DATA_TABLES:
        got = dict(ctx.db.execute(f"SELECT year, count(*) FROM {table} GROUP BY year").fetchall())
        exp = ctx.unit[table].groupby("year").size().to_dict()
        check(ctx, f"G6 {table} rows per year = rows prepared", got == exp,
              ", ".join(f"{y}: {got.get(y, 0)}" for y in YEARS))
        dup = q(f"SELECT count(*) - count(DISTINCT ({TABLE_KEYS[table]})) FROM {table}")
        check(ctx, f"G6 {table} no duplicate keys", dup == 0, f"{dup} duplicate key(s)")
    for year in YEARS:
        exp = ctx.expected[("FARS", year, "ped_fatalities")]
        got = q("SELECT count(*) FROM pedestrian WHERE year = %s", year)
        check(ctx, f"G6 {year} pedestrian rows = expected total", got == exp, f"expected {exp:,}, table {got:,}")
    for view, blocking in [("v_dq_count_mismatch", True), ("v_dq_unlabeled_code", True), ("v_dq_population_gap", True),
                           ("v_dq_county_block_group_mismatch", True), ("v_dq_missing_typing", False),
                           ("v_dq_no_striking_vehicle", False)]:
        n = q(f"SELECT count(*) FROM {view}")
        sample = ctx.db.execute(f"SELECT * FROM {view} LIMIT 5").fetchall() if n else []
        check(ctx, f"G6 {view} returns no rows", n == 0,
              f"{n} row(s)" + (f"; first: {sample}" if sample else ""), blocking=blocking)
    n = q("SELECT count(*) FROM crash c WHERE NOT EXISTS (SELECT 1 FROM pedestrian p WHERE (p.year, p.st_case) = (c.year, c.st_case)) "
          "OR NOT EXISTS (SELECT 1 FROM vehicle v WHERE (v.year, v.st_case) = (c.year, c.st_case))")
    check(ctx, "G6 every crash has >= 1 pedestrian and >= 1 vehicle", n == 0, f"{n} crash(es) without")
    deaths, rated = q("SELECT count(*) FROM pedestrian"), q("SELECT coalesce(sum(deaths_all), 0) FROM v_county_rate")
    check(ctx, "G6 county rates cover every death", deaths == rated, f"{rated:,} in v_county_rate, {deaths:,} pedestrian rows")
    nf = q("SELECT count(*) FROM source_file WHERE run_id = %s AND source = 'FARS'", ctx.run_id)
    rel = q("SELECT release FROM source_file WHERE run_id = %s AND data_year = 2024", ctx.run_id)
    check(ctx, "G6 lineage: 5 FARS source_file rows for this run, 2024 release recorded", nf == 5 and rel is not None,
          f"{nf} FARS file(s); 2024 release = {rel}")
    total, with_bg = ctx.db.execute("SELECT count(*), count(geoid10) FROM crash").fetchone()
    share = round(100.0 * with_bg / total, 1) if total else 0.0
    check(ctx, "G6 share of crashes with a block group >= 90%", share >= 90, f"{share}% (EPA join not run yet)", blocking=False)
    unk = ctx.db.execute("SELECT year, round(100.0 * count(*) FILTER (WHERE c.rur_urb IN (6, 8, 9)) / count(*), 1) "
                         "FROM pedestrian p JOIN crash c USING (year, st_case) GROUP BY year ORDER BY year").fetchall()
    ctx.log.step("RUR_URB not reported, % of deaths by year (cleaning plan, issue 2): "
                 + ", ".join(f"{y}: {r}" for y, r in unk))
    if ctx.checks_failed:
        ctx.db.rollback()
        ctx.log.step("post-load checks failed: load transaction ROLLED BACK", status="error")
        gate(ctx, "G6 post-load verification")
    # The run's status changes inside the load transaction, so data and status commit together:
    # a crash after this point leaves a 'succeeded' run, never a committed load marked 'running'.
    ctx.db.execute("UPDATE etl_run SET status = 'succeeded', finished_at = now() WHERE run_id = %s", (ctx.run_id,))
    ctx.db.commit()
    ctx.committed = True
    ctx.log.step("all post-load checks passed: load transaction COMMITTED, etl_run status = succeeded")


def s_finalize(ctx: Ctx) -> None:
    counts, combined = fingerprint(ctx.bk)
    for t, (n, h) in counts.items():
        ctx.log.step(f"{t}: {n:,} rows, content md5 {h}", rows_out=n)
    ctx.log.step(f"fingerprint of the data tables after the run: {combined}"
                 + (" (identical to before the run: the rerun changed nothing)" if combined == ctx.fingerprint_before else ""))
    file_of = {int(s["data_year"]): s for s in ctx.sources if s["source"] == "FARS"}
    for year in YEARS:
        ctx.log.step(f"lineage {year}: {file_of[year]['file_name']} sha256 {file_of[year]['sha256'][:12]} ({file_of[year]['release']}) "
                     f"-> person {ctx.national[(year, 'person')]:,} national -> {len(ctx.raw[year]['person']):,} Florida "
                     f"-> {int((ctx.unit['pedestrian']['year'] == year).sum()):,} pedestrian fatalities loaded")


STAGES = [
    Stage("preflight", [], "-", "connect, take the run lock, close abandoned runs, open the etl_run row", s_preflight),
    Stage("verify_sources", ["preflight"], "G1", "every input file present; size and SHA-256 equal to sources.csv", s_verify_sources),
    Stage("extract", ["verify_sources"], "G2", "read the CSV members from the zips (UTF-8, cp1252 fallback); required columns present; keep STATE = 12", s_extract),
    Stage("reconcile_inventory", ["extract"], "G3", "Florida rows per member equal expected_counts.csv", s_reconcile_inventory),
    Stage("transform", ["reconcile_inventory"], "-", "unit of observation; filler coordinates and STR_VEH 0 -> NULL; census to long format", s_transform),
    Stage("join_block_groups", ["transform"], "-", "EPA spatial join for crash.geoid10 (skipped until the EPA file is in sources.csv)", s_join_block_groups),
    Stage("validate_records", ["transform"], "G4", "pandera: unique keys, no orphans, types, code lists valid for the year, reference tables; failures -> rejected_record", s_validate_records),
    Stage("reconcile_unit", ["validate_records"], "G5", "pedestrian fatalities and crashes per year equal the published totals", s_reconcile_unit),
    Stage("load", ["reconcile_unit", "join_block_groups"], "-", "ONE transaction: delete 2020-2024, insert, run the deferred triggers", s_load),
    Stage("verify_load", ["load"], "G6", "post-load checks inside the same transaction; COMMIT only if all blocking checks pass", s_verify_load),
    Stage("finalize", ["verify_load"], "-", "row counts, content fingerprints, lineage lines; etl_run = succeeded", s_finalize),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def read_expected(path: Path) -> dict:
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[(r["source"], int(r["data_year"]) if r["data_year"] else None, r["measure"])] = int(r["expected"])
    return out


def run(args) -> int:
    log = RunLog(Path(args.log_dir))
    log.redact = bool(getattr(args, "redact_keys", False))
    ctx = Ctx(args=args, log=log)
    done: set[str] = set()
    current = None
    try:
        for st in STAGES:
            assert all(d in done for d in st.deps), f"stage {st.name} scheduled before its dependencies"
            current = st
            log.stage = st.name
            t0 = time.perf_counter()
            log.info(f"start ({st.doc})")
            result = st.fn(ctx)
            done.add(st.name)
            secs = time.perf_counter() - t0
            if ctx.run_id:
                log.step(f"stage {st.name} {'skipped' if result == 'skipped' else 'finished'} in {secs:.2f}s"
                         + (f"; gate {st.gate} passed" if st.gate != "-" else ""),
                         status="warning" if result == "skipped" else "ok")
            if args.simulate_crash_after == st.name:
                log.error(f"SIMULATED CRASH after stage {st.name}: the process exits now without cleaning up "
                          + ("(the load is already committed, together with status 'succeeded')" if ctx.committed else
                             "(PostgreSQL rolls back any open load transaction when the connection drops)"))
                os._exit(70)
        log.stage = "end"
        log.info(f"RUN {ctx.run_id} SUCCEEDED; log file {log.path}")
        return 0
    except SystemExit as e:
        return int(e.code or 1)
    except BaseException as e:  # noqa: BLE001 - every failure, Ctrl-C included, must end the run cleanly
        stage = current.name if current else "-"
        if ctx.committed:
            # Only reporting can fail after the COMMIT; the load and its 'succeeded' status are already permanent.
            log.warn(f"{type(e).__name__} after the load was committed (stage {stage}): {e}. The data and the run "
                     f"status 'succeeded' are already committed; only the report lines after this point are missing.")
            return 0
        kind = "gate failed" if isinstance(e, GateFailed) else f"error ({type(e).__name__})"
        try:
            if ctx.db is not None and not ctx.db.closed:
                ctx.db.rollback()
        except Exception:  # noqa: BLE001 - a dead connection has rolled back already
            pass
        if not isinstance(e, GateFailed):
            for ln in traceback.format_exc().rstrip().splitlines():
                log.error(ln)
        if ctx.bk is None or ctx.run_id is None:
            log.error(f"run could not start: {e}")
            return 2
        try:
            if ctx.bk.closed or ctx.bk.broken:            # the bookkeeping connection itself died: open a new one
                ctx.bk = psycopg.connect(conninfo(ctx.args), autocommit=True)
                ctx.log.bk = ctx.bk
            log.step(f"{kind} at stage {stage}: {e}", status="error")
            counts, after = fingerprint(ctx.bk)
            last = ctx.bk.execute("SELECT max(run_id) FROM etl_run WHERE status = 'succeeded'").fetchone()[0]
            same = (after == ctx.fingerprint_before) if ctx.fingerprint_before else None
            log.step(f"data tables unchanged by this run: {same if same is not None else 'not measured'} "
                     f"(fingerprint {after[:12]}); they hold the load of run {last if last else '(none yet)'}",
                     step="rollback-check")
            ctx.bk.execute("UPDATE etl_run SET status = 'failed', finished_at = now() WHERE run_id = %s", (ctx.run_id,))
        except Exception as e2:  # noqa: BLE001
            log.error(f"could not record the failure in the database ({type(e2).__name__}: {e2}); "
                      f"run {ctx.run_id} stays 'running' and the next run will close it as abandoned")
        log.stage = "end"
        log.error(f"RUN {ctx.run_id} FAILED at stage {stage}; see docs/Week7_Pipeline_Shkirpan.md, section 6 (recovery)")
        return 1
    finally:
        for conn in (ctx.db, ctx.bk):                     # closing the session also releases the advisory lock
            try:
                if conn is not None and not conn.closed:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Read-only commands
# ---------------------------------------------------------------------------
def table(rows, headers) -> str:
    rows = [["" if v is None else str(v) for v in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = lambda r: " | ".join(v.ljust(w[i]) for i, v in enumerate(r))
    return "\n".join([line(headers), "-+-".join("-" * x for x in w)] + [line(r) for r in rows])


def cmd_stages(_args) -> int:
    for i, st in enumerate(STAGES, 1):
        print(f"{i:>2}. {st.name:<20} gate {st.gate:<3} after: {', '.join(st.deps) or '(start)'}\n      {st.doc}")
    return 0


def cmd_status(args) -> int:
    with psycopg.connect(conninfo(args)) as c:
        print(table(c.execute("SELECT run_id, status, started_at::timestamp(0), finished_at::timestamp(0), "
                              "left(git_commit, 7) FROM etl_run ORDER BY run_id DESC LIMIT 12").fetchall(),
                    ["run_id", "status", "started_at", "finished_at", "commit"]))
        rid = args.run or c.execute("SELECT max(run_id) FROM etl_run").fetchone()[0]
        if rid is None:
            return 0
        print(f"\nrun {rid}: etl_log")
        print(table(c.execute("SELECT log_id, logged_at::time(0), step, rows_in, rows_out, status, left(message, 110) "
                              "FROM etl_log WHERE run_id = %s ORDER BY log_id", (rid,)).fetchall(),
                    ["log_id", "time", "step", "rows_in", "rows_out", "status", "message"]))
        print(f"\nrun {rid}: validation_result")
        print(table(c.execute("SELECT count(*) FILTER (WHERE passed), count(*) FILTER (WHERE NOT passed) "
                              "FROM validation_result WHERE run_id = %s", (rid,)).fetchall(), ["passed", "failed"]))
        bad = c.execute("SELECT check_name, left(detail, 100) FROM validation_result WHERE run_id = %s AND NOT passed "
                        "ORDER BY result_id", (rid,)).fetchall()
        if bad:
            print(table(bad, ["failed check", "detail"]))
        n = c.execute("SELECT count(*) FROM rejected_record WHERE run_id = %s", (rid,)).fetchone()[0]
        print(f"\nrejected records in run {rid}: {n}" + ("  (python pipeline/etl.py rejected --run %d)" % rid if n else ""))
    return 0


def cmd_rejected(args) -> int:
    with psycopg.connect(conninfo(args)) as c:
        rid = args.run or c.execute("SELECT max(run_id) FROM rejected_record").fetchone()[0]
        rows = c.execute("SELECT reject_id, data_year, file_name || ':' || member, source_line, target_table, record_key, "
                         "check_name, column_name, failure_value FROM rejected_record WHERE run_id = %s ORDER BY reject_id",
                         (rid,)).fetchall()
        if args.redact_keys:                         # key, CSV line and value would point to one real record
            rows = [r[:3] + ("-",) + r[4:5] + ("<masked>",) + r[6:8] + ("<masked>",) for r in rows]
        print(f"run {rid}: {len(rows)} rejected record(s)")
        print(table(rows, ["id", "year", "file:member", "line", "target", "key", "check", "column", "value"]))
    return 0


def cmd_snapshot(args) -> int:
    with psycopg.connect(conninfo(args)) as c:
        counts, combined = fingerprint(c)
        per_year = {t: dict(c.execute(f"SELECT year, count(*) FROM {t} GROUP BY year").fetchall()) for t in DATA_TABLES}
        rows = [[t, n] + [per_year[t].get(y, 0) for y in YEARS] + [h[:12]] for t, (n, h) in counts.items()]
        print(table(rows, ["table", "rows"] + [str(y) for y in YEARS] + ["content md5"]))
        print(f"fingerprint of all data tables: {combined}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", help="libpq connection string (default: PG* environment variables, database ped_safety)")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="run the pipeline")
    r.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    r.add_argument("--sources", default=str(ROOT / "pipeline" / "sources.csv"), help="pinned input files with SHA-256")
    r.add_argument("--expected", default=str(ROOT / "pipeline" / "expected_counts.csv"), help="reconciliation totals")
    r.add_argument("--log-dir", default=str(ROOT / "logs"))
    r.add_argument("--redact-keys", action="store_true", help="mask case numbers in the log (for evidence published from real data)")
    r.add_argument("--simulate-crash-after", choices=[s.name for s in STAGES], help="fault injection for the restart test")
    sub.add_parser("stages", help="print the stages, gates and dependencies")
    for name, helptext in [("status", "show runs and the steps of one run"), ("rejected", "list quarantined records")]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--run", type=int)
        if name == "rejected":
            p.add_argument("--redact-keys", action="store_true", help="mask case numbers and values")
    sub.add_parser("snapshot", help="row counts and content fingerprints of the data tables")
    args = ap.parse_args(argv)
    if args.cmd in (None, "run"):
        if args.cmd is None:
            args = ap.parse_args(["run"] + (argv or sys.argv[1:]))
        return run(args)
    return {"stages": cmd_stages, "status": cmd_status, "rejected": cmd_rejected, "snapshot": cmd_snapshot}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
