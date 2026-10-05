#!/usr/bin/env python3
"""
run_scenarios.py - Week 7 evidence: runs the pipeline through six scenarios and keeps the logs.

    python pipeline/run_scenarios.py --synthetic   # synthetic inputs (tools/make_synthetic_raw.py) -> docs/evidence/week7_synthetic/
    python pipeline/run_scenarios.py               # the real files in data/raw/ (pipeline/sources.csv) -> docs/evidence/week7/

The scenarios run in their own database, ped_safety_week7 (created if missing, rebuilt every time with
sql/00_build_all.sql), so the project database ped_safety is never touched. Connection settings:
PGHOST, PGPORT, PGUSER, or ~/.pgpass, as for etl.py. Every scenario ends with CHECK lines that compare
what happened with what was expected; the script exits 1 if any check fails.

  1  first run on an empty database                          -> must succeed
  2  rerun with the same inputs                              -> must succeed, tables byte-for-byte identical
  3  failure A: a raw file edited after it was pinned        -> gate G1 stops the run before any read
  4  failure B: a new file version with four bad records     -> gate G4 quarantines them, nothing is published
  5  interrupted run: process killed inside the load         -> PostgreSQL rolls the open transaction back
  6  restart: the same command again                         -> closes the abandoned run, succeeds, same tables
  7  run history from the bookkeeping tables

Failure inputs are made from copies in data/interim/ (ignored by Git); the pinned files are never touched.
With real data, record keys are masked in the evidence (--redact-keys), because a FARS case number
points to a real death; the unmasked keys stay in the local rejected_record table.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ETL = [sys.executable, str(ROOT / "pipeline" / "etl.py")]


def sh(cmd: list[str], out: io.StringIO | None = None, check: bool = True) -> int:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = p.stdout + p.stderr
    if out is not None:
        out.write(text)
    if check and p.returncode != 0:
        sys.stderr.write(text)
        raise SystemExit(f"command failed ({p.returncode}): {' '.join(cmd)}")
    return p.returncode


def file_sha(path: Path) -> str:
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Making the failure inputs (works on the real zips and on the synthetic ones)
# ---------------------------------------------------------------------------
def _read(zf: zipfile.ZipFile, base: str):
    name = next(m for m in zf.namelist() if Path(m).name.lower() == f"{base}.csv")
    raw = zf.read(name)
    for enc in ("utf-8", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text, newline="")))
    col = {h.strip().upper(): i for i, h in enumerate(rows[0])}
    return name, enc, rows, col


def _write_zip(src: Path, dst: Path, replaced: dict[str, bytes]) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, replaced.get(info.filename, zin.read(info.filename)), compress_type=zipfile.ZIP_DEFLATED)


def _csv_bytes(rows, enc) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return buf.getvalue().encode(enc)


def _ped_rows(rows, col):
    return [i for i, r in enumerate(rows[1:], 1)
            if r[col["STATE"]].strip() == "12" and r[col["PER_TYP"]].strip() == "5" and r[col["INJ_SEV"]].strip() == "4"]


def tamper(src: Path, dst: Path) -> str:
    """Change one AGE value in person.csv and re-zip: what an accidental 'open in Excel and save' does."""
    with zipfile.ZipFile(src) as zf:
        name, enc, rows, col = _read(zf, "person")
    i = _ped_rows(rows, col)[0]
    old = rows[i][col["AGE"]]
    rows[i][col["AGE"]] = "47" if old.strip() != "47" else "48"
    _write_zip(src, dst, {name: _csv_bytes(rows, enc)})
    return f"{src.name}: person.csv line {i + 1}, AGE {old.strip()} -> {rows[i][col['AGE']]}"


def inject_defects(src: Path, dst: Path) -> list[str]:
    """Four bad records, one per cleaning-plan issue, in a copy of one FARS zip."""
    with zipfile.ZipFile(src) as zf:
        an, aenc, acc, ac = _read(zf, "accident")
        pn, penc, per, pc = _read(zf, "person")
        bn, benc, pbt, bc = _read(zf, "pbtype")
    peds = _ped_rows(per, pc)
    cases = []
    for i in peds:                                    # four different crashes
        c = per[i][pc["ST_CASE"]].strip()
        if c not in [x[1] for x in cases]:
            cases.append((i, c))
        if len(cases) == 4:
            break
    (ia, ca), (ib, cb), (ic, cc), (id_, cd) = cases
    used = {r[ac["ST_CASE"]].strip() for r in acc[1:] if r[ac["STATE"]].strip() == "12"}
    orphan = next(str(n) for n in range(129999, 120000, -1) if str(n) not in used)
    notes = []
    # (a) issue 3: an exact duplicate of a pedestrian-fatality person row
    per.insert(ia + 1, list(per[ia]))
    notes.append(f"(a) duplicate person row: ST_CASE {ca} VEH_NO {per[ia][pc['VEH_NO']].strip()} PER_NO {per[ia][pc['PER_NO']].strip()}")
    # (b) issue 4 and (c) rule 3: an undocumented light code and an unknown county on two crashes
    for r in acc[1:]:
        if r[ac["STATE"]].strip() == "12" and r[ac["ST_CASE"]].strip() == cb:
            notes.append(f"(b) accident ST_CASE {cb}: LGT_COND {r[ac['LGT_COND']].strip()} -> 42 (no label in code_lookup)")
            r[ac["LGT_COND"]] = "42"
        if r[ac["STATE"]].strip() == "12" and r[ac["ST_CASE"]].strip() == cc:
            notes.append(f"(c) accident ST_CASE {cc}: COUNTY {r[ac['COUNTY']].strip()} -> 999 (FARS 'unknown', not a Florida county)")
            r[ac["COUNTY"]] = "999"
    # (d) rule 1: a pedestrian fatality (and its typing record) whose crash is not in accident.csv
    o = list(per[id_ + 1 if id_ > ia else id_])
    o[pc["ST_CASE"]] = orphan
    per.append(o)
    src_b = next(r for r in pbt[1:] if r[bc["STATE"]].strip() == "12" and r[bc["ST_CASE"]].strip() == cd)
    ob = list(src_b)
    ob[bc["ST_CASE"]] = orphan
    pbt.append(ob)
    notes.append(f"(d) orphan person + pbtype rows: ST_CASE {orphan} does not exist in accident.csv")
    _write_zip(src, dst, {an: _csv_bytes(acc, aenc), pn: _csv_bytes(per, penc), bn: _csv_bytes(pbt, benc)})
    return notes


def redact(text: str) -> str:
    return re.sub(r"\b12\d{4}\b", "12xxxx", text)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--synthetic", action="store_true", help="generate and use synthetic inputs")
    ap.add_argument("--db", default="ped_safety_week7",
                    help="database to (re)build for the scenarios (default ped_safety_week7, created if missing; "
                         "kept apart from ped_safety so the project database is never overwritten)")
    ap.add_argument("--psql", default="psql", help="path to psql (Windows: e.g. C:/Program Files/PostgreSQL/16/bin/psql.exe)")
    args = ap.parse_args()
    import psycopg
    with psycopg.connect("dbname=postgres", autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (args.db,)).fetchone():
            c.execute(f'CREATE DATABASE "{args.db}"')
    os.environ["PGDATABASE"] = args.db                         # etl.py and psql below use this database

    if args.synthetic:
        raw = ROOT / "data" / "synthetic" / "clean"
        sh([sys.executable, str(ROOT / "tools" / "make_synthetic_raw.py"), "--out", str(raw)])
        sources, expected = raw / "sources.csv", raw / "expected_counts.csv"
        out_dir, label = ROOT / "docs" / "evidence" / "week7_synthetic", "SYNTHETIC files from tools/make_synthetic_raw.py (not real FARS rows)"
        extra = []
    else:
        raw, sources, expected = ROOT / "data" / "raw", ROOT / "pipeline" / "sources.csv", ROOT / "pipeline" / "expected_counts.csv"
        out_dir, label = ROOT / "docs" / "evidence" / "week7", "REAL files in data/raw/, pinned by pipeline/sources.csv (case numbers, lines and values masked)"
        extra = ["--redact-keys"]
    real = bool(extra)

    # 0. clean database first; the old evidence is removed only once the rebuild has worked
    sh([args.psql, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", "sql/00_build_all.sql"])
    interim = ROOT / "data" / "interim" / "week7"
    shutil.rmtree(interim, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.log"):
        old.unlink()
    shutil.rmtree(out_dir / "runs", ignore_errors=True)
    log_dir = interim / "logs"
    rel = lambda p: os.path.relpath(p, ROOT)                 # etl.py runs from the repository root
    base = ["run", "--raw-dir", rel(raw), "--sources", rel(sources), "--expected", rel(expected), "--log-dir", rel(log_dir)] + extra
    checks: list[tuple[str, bool, str]] = []
    db = psycopg.connect("", autocommit=True)
    q = lambda sql, *a: db.execute(sql, a or None).fetchone()[0]

    def expect(name: str, ok: bool, detail: str, buf) -> None:
        checks.append((name, ok, detail))
        buf.write(f"CHECK {'PASS' if ok else 'FAIL'}  {name}: {detail}\n")

    def scenario(fname: str, title: str, expect_text: str, steps) -> None:
        buf = io.StringIO()
        buf.write(f"# {title}\n# input: {label}\n# expected outcome: {expect_text}\n"
                  f"# recorded {datetime.now().astimezone().isoformat(timespec='seconds')}\n\n")
        steps(buf)
        text = buf.getvalue().replace(str(ROOT) + os.sep, "").replace(str(ROOT), ".")
        (out_dir / fname).write_text(redact(text) if real else text, encoding="utf-8")
        print(f"wrote {out_dir / fname}")

    def etl(buf, argv, note=""):
        shown = " ".join(["python pipeline/etl.py"] + [str(a).replace(str(ROOT) + os.sep, "") for a in argv])
        buf.write(f"$ {shown}{note}\n")
        out = io.StringIO()
        rc = sh(ETL + argv, out, check=False)
        buf.write(out.getvalue() + f"[exit code {rc}]\n\n")
        return rc, out.getvalue()

    def snap(buf, title="tables after this scenario") -> str:
        buf.write(f"--- {title} ---\n")
        _, out = etl(buf, ["snapshot"])
        return out.rsplit("fingerprint of all data tables: ", 1)[-1].strip()

    state = {}

    def s1(b):
        b.write(f"server: {q('SELECT version()')}\n\n")
        rc, _ = etl(b, base)
        state["fp"] = snap(b)
        expect("exit code 0", rc == 0, f"exit {rc}", b)
        expect("run 1 recorded as succeeded", q("SELECT status FROM etl_run WHERE run_id = 1") == "succeeded", "etl_run 1", b)
    scenario("01_first_run.log", "Scenario 1: first end-to-end run on an empty database", "exit 0, all gates pass", s1)

    def s2(b):
        before = snap(b, "tables before the rerun")
        rc, out = etl(b, base)
        after = snap(b, "tables after the rerun")
        expect("exit code 0", rc == 0, f"exit {rc}", b)
        expect("content fingerprint identical to scenario 1", before == after == state["fp"], f"{after}", b)
        expect("every table and year replaced, not appended", out.count("deleted ") == out.count("inserted ") > 0,
               f"{out.count('deleted ')} delete/insert lines", b)
    scenario("02_rerun_same_inputs.log", "Scenario 2: rerun with exactly the same inputs (duplicate prevention)",
             "exit 0; every year deleted and re-inserted; counts and content fingerprints identical to scenario 1", s2)

    def f1(b):
        dst = interim / "tampered"
        shutil.copytree(raw, dst)
        target = sorted(dst.glob("FARS2022*.zip"))[0]
        tmp = target.with_suffix(".tmp")
        note = tamper(target, tmp)
        tmp.replace(target)
        note = f"{target.name}: one AGE value in person.csv changed and the zip re-written" if real else note
        b.write(f"fault injected: {note}\n(sources.csv is NOT updated: the pinned hash no longer matches)\n\n")
        rc, out = etl(b, base[:2] + [rel(dst)] + base[3:])
        fp = snap(b)
        expect("exit code 1", rc == 1, f"exit {rc}", b)
        expect("stopped by G1 at verify_sources", "FAIL  G1 sha256 FARS2022" in out and "FAILED at stage verify_sources" in out, "log lines", b)
        expect("tables unchanged (fingerprint of scenario 1)", fp == state["fp"], fp, b)
    scenario("03_failure_tampered_file.log", "Scenario 3 (deliberate failure A): a raw file edited after it was pinned",
             "exit 1 at stage verify_sources (gate G1); nothing read, nothing loaded; tables unchanged", f1)

    def f2(b):
        dst = interim / "defects"
        shutil.copytree(raw, dst)
        target = sorted(dst.glob("FARS2023*.zip"))[0]
        tmp = target.with_suffix(".tmp")
        notes = inject_defects(target, tmp)
        tmp.replace(target)
        if real:                                       # keep keys and original values of real records out of the evidence
            notes = [f"({c}) {d}" for c, d in zip("abcd", [
                "duplicate of a pedestrian-fatality person row", "LGT_COND set to 42 (no label in code_lookup)",
                "COUNTY set to 999 (FARS 'unknown')", "orphan person + pbtype rows (case not in accident.csv)"])]
        # the new version is accepted into a copy of the manifest, as a re-download would be
        rows = list(csv.DictReader(open(sources, newline="", encoding="utf-8")))
        for r in rows:
            if r["file_name"] == target.name:
                r["sha256"], r["bytes"] = file_sha(target), str(target.stat().st_size)
        with open(dst / "sources.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        exp = list(csv.DictReader(open(expected, newline="", encoding="utf-8")))
        bump = {"person_fl_rows": 2, "pbtype_fl_rows": 1}          # the duplicate and the orphan rows
        for r in exp:
            if r["data_year"] == "2023" and r["measure"] in bump:
                r["expected"] = str(int(r["expected"]) + bump[r["measure"]])
        with open(dst / "expected_counts.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(exp[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(exp)
        b.write("faults injected into " + target.name + ":\n  " + "\n  ".join(notes) +
                "\n(the file's new hash and row inventory are accepted into a copy of sources.csv / expected_counts.csv,"
                "\n so gates G1-G3 pass and the record-level gate G4 has to catch the defects)\n\n")
        rc, out = etl(b, ["run", "--raw-dir", rel(dst), "--sources", rel(dst / "sources.csv"),
                          "--expected", rel(dst / "expected_counts.csv"), "--log-dir", rel(log_dir)] + extra)
        b.write("--- quarantine ---\n")
        etl(b, ["rejected"] + extra)
        fp = snap(b)
        rid = q("SELECT max(run_id) FROM etl_run")
        n = q("SELECT count(*) FROM rejected_record WHERE run_id = %s", rid)
        kinds = {r[0] for r in db.execute("SELECT check_name FROM rejected_record WHERE run_id = %s", (rid,)).fetchall()}
        expect("exit code 1", rc == 1, f"exit {rc}", b)
        expect("stopped by G4 at validate_records", "FAILED at stage validate_records" in out, "log line", b)
        expect("all four defects quarantined (5 records: the orphan death brings its typing record)", n == 5 and len(kinds) == 4,
               f"{n} rejected_record rows, {len(kinds)} distinct rules", b)
        expect("tables unchanged (fingerprint of scenario 1)", fp == state["fp"], fp, b)
    scenario("04_failure_bad_records.log", "Scenario 4 (deliberate failure B): a new file version with four bad records",
             "exit 1 at stage validate_records (gate G4); bad records in rejected_record; nothing published", f2)

    def s5(b):
        rc, _ = etl(b, base + ["--simulate-crash-after", "load"], "   # fault injection")
        fp = snap(b)
        etl(b, ["status"])
        rid = q("SELECT max(run_id) FROM etl_run")
        expect("exit code 70 (process killed)", rc == 70, f"exit {rc}", b)
        expect("uncommitted load rolled back: tables unchanged", fp == state["fp"], fp, b)
        expect("etl_run row left 'running'", q("SELECT status FROM etl_run WHERE run_id = %s", rid) == "running", f"run {rid}", b)
        state["killed"] = rid
    scenario("05_interrupted_run.log", "Scenario 5: the process dies inside the load transaction",
             "exit 70 after stage load (before COMMIT); PostgreSQL rolls back; etl_run row left 'running'; tables unchanged", s5)

    def s6(b):
        rc, out = etl(b, base)
        fp = snap(b)
        expect("exit code 0", rc == 0, f"exit {rc}", b)
        expect("abandoned run closed as failed", "recovered abandoned run" in out and
               q("SELECT status FROM etl_run WHERE run_id = %s", state["killed"]) == "failed", f"run {state['killed']}", b)
        expect("tables identical to scenarios 1-2", fp == state["fp"], fp, b)
    scenario("06_restart_after_interrupt.log", "Scenario 6: restart = the same command again",
             "exit 0; the abandoned run is closed as failed; tables identical to scenarios 1-2", s6)

    def history(b):
        etl(b, ["status"])
        b.write("--- every run: steps with row counts (etl_log) and checks (validation_result) ---\n")
        sq = ("SELECT r.run_id, r.status, r.started_at::timestamp(0) AS started, r.finished_at::timestamp(0) AS finished, "
              "(SELECT count(*) FROM etl_log l WHERE l.run_id = r.run_id) AS log_rows, "
              "(SELECT count(*) FROM etl_log l WHERE l.run_id = r.run_id AND l.status = 'error') AS errors, "
              "(SELECT count(*) FROM validation_result v WHERE v.run_id = r.run_id AND v.passed) AS checks_passed, "
              "(SELECT count(*) FROM validation_result v WHERE v.run_id = r.run_id AND NOT v.passed) AS checks_failed, "
              "(SELECT count(*) FROM rejected_record x WHERE x.run_id = r.run_id) AS rejected, "
              "(SELECT count(*) FROM source_file s WHERE s.run_id = r.run_id) AS files "
              "FROM etl_run r ORDER BY r.run_id")
        b.write(subprocess.run([args.psql, "-X", "-c", sq], cwd=ROOT, capture_output=True, text=True).stdout + "\n")
        q2 = ("SELECT run_id, to_char(logged_at, 'HH24:MI:SS.MS') AS at, step, rows_in, rows_out, status, left(message, 120) AS message "
              "FROM etl_log WHERE status <> 'ok' OR step IN ('load', 'finalize') ORDER BY log_id")
        b.write(subprocess.run([args.psql, "-X", "-c", q2], cwd=ROOT, capture_output=True, text=True).stdout)
        st = [r[0] for r in db.execute("SELECT status FROM etl_run ORDER BY run_id").fetchall()]
        expect("run statuses", st == ["succeeded", "succeeded", "failed", "failed", "failed", "succeeded"], ", ".join(st), b)
        b.write("\n--- all scenario checks ---\n" + "".join(f"CHECK {'PASS' if ok else 'FAIL'}  {n}: {d}\n" for n, ok, d in checks))
    scenario("07_run_history.log", "Run history from the bookkeeping tables (etl_run, etl_log, validation_result, rejected_record)",
             "runs 1, 2, 6 succeeded; 3, 4, 5 failed (5 closed by run 6)", history)

    (out_dir / "runs").mkdir(exist_ok=True)
    for f in sorted(log_dir.glob("run_*.log")):
        text = f.read_text(encoding="utf-8").replace(str(ROOT) + os.sep, "")
        stable = re.sub(r"^(run_\d{4})_.*\.log$", r"\1.log", f.name)      # drop the start time from the name
        (out_dir / "runs" / stable).write_text(redact(text) if real else text, encoding="utf-8")
    print(f"per-run log files copied to {out_dir / 'runs'}")
    failed = [n for n, ok, _ in checks if not ok]
    print(f"scenario checks: {len(checks) - len(failed)} passed, {len(failed)} failed" + (f": {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
