#!/usr/bin/env python3
"""
trace.py - Week 8: follow ONE record through the pipeline, from the raw CSV line to the
analysis view, quoting the evidence at every hop. Read-only: it changes nothing.

    python pipeline/trace.py --pick normal               # a typical death: every link present
    python pipeline/trace.py --pick edge                 # filler coordinates -> NULL point, death kept
    python pipeline/trace.py --year 2021 --st-case 120093
    python pipeline/trace.py --pick normal --raw-dir "E:\\College\\Data Management\\raw"
    python pipeline/trace.py --pick edge --redact        # mask case numbers in the output

The trace prints, in pipeline order:
  1  lineage      which run loaded the record, from which file (SHA-256, release, G1)
  2  raw          the record's own lines in accident/vehicle/person/pbtype inside the zip
  3  transform    each cleaning rule next to its effect on this record (raw value -> stored value)
  4  database     the stored rows and the constraints that guard them
  5  view         the items the record contributes to v_ped_transactions, or why it is out of scope
  6  aggregates   the county-rate row this death is counted in

Connection: PG* environment variables or --dsn, like etl.py (default database ped_safety).
--raw-dir may be omitted: steps 2-3 then quote only the stored values, and say so.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import zipfile
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ["accident", "vehicle", "person", "pbtype"]
# Columns quoted from each raw member: the ones the pipeline loads (etl.py REQUIRED).
RAW_COLS = {
    "accident": ["ST_CASE", "COUNTY", "MONTH", "DAY_WEEK", "HOUR", "RUR_URB", "FUNC_SYS",
                 "RELJCT2", "LGT_COND", "WEATHER", "LATITUDE", "LONGITUD", "TWAY_ID", "FATALS", "PEDS"],
    "vehicle": ["ST_CASE", "VEH_NO", "BODY_TYP", "VSPD_LIM", "HIT_RUN"],
    "person": ["ST_CASE", "VEH_NO", "PER_NO", "PER_TYP", "INJ_SEV", "AGE", "SEX", "DRINKING", "STR_VEH"],
    "pbtype": ["ST_CASE", "VEH_NO", "PER_NO", "PBCWALK", "PBSWALK", "PEDLOC", "PEDPOS", "PEDCTYPE"],
}
LAT_FILLERS = {"77.7777", "88.8888", "99.9999"}
LON_FILLERS = {"777.7777", "888.8888", "999.9999"}


REDACT = False


def out(line: str = "", redact: bool | None = None) -> None:
    if REDACT if redact is None else redact:
        line = re.sub(r"\b12\d{4}\b", "12xxxx", line)
    print(line)


def die(msg: str) -> None:
    sys.exit(re.sub(r"\b12\d{4}\b", "12xxxx", msg) if REDACT else msg)


def q1(conn, sql, *args):
    return conn.execute(sql, args or None).fetchone()


def qall(conn, sql, *args):
    return conn.execute(sql, args or None).fetchall()


def cols_of(conn, table: str) -> list[str]:
    return [r[0] for r in qall(conn, "SELECT column_name FROM information_schema.columns "
                                     "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position", table)]


def pick(conn, kind: str):
    """Choose a record the way the demo needs it: 'normal' has every link, 'edge' lost its point."""
    if kind == "normal":
        row = q1(conn, """
            SELECT p.year, p.st_case FROM pedestrian p
            JOIN crash c USING (year, st_case)
            WHERE c.rur_urb = 2 AND c.func_sys BETWEEN 3 AND 7
              AND p.str_veh IS NOT NULL AND c.latitude IS NOT NULL
              AND (SELECT count(*) FROM pedestrian x WHERE (x.year, x.st_case) = (p.year, p.st_case)) = 1
            ORDER BY p.year, p.st_case LIMIT 1""")
        why = "a typical in-scope death: urban non-freeway crash, striking vehicle resolved, usable coordinates"
    else:
        row = q1(conn, """
            SELECT p.year, p.st_case FROM pedestrian p
            JOIN crash c USING (year, st_case)
            WHERE c.latitude IS NULL
            ORDER BY (SELECT max(v.hit_run) FROM vehicle v WHERE (v.year, v.st_case) = (p.year, p.st_case)) DESC,
                     p.year, p.st_case LIMIT 1""")
        why = "an edge case: FARS filler coordinates became NULL, so there is no point and no block group, but the death is kept"
        if row is None:
            row = q1(conn, """SELECT year, st_case FROM pedestrian GROUP BY year, st_case
                              HAVING count(*) >= 2 ORDER BY year, st_case LIMIT 1""")
            why = "an edge case: one crash, several deaths (one transaction per death, shared scene)"
    if row is None:
        die("no matching record in the database; is it loaded?")
    return row[0], row[1], why


def find_member(zf: zipfile.ZipFile, name: str) -> str | None:
    for m in zf.namelist():
        if Path(m).name.lower() == f"{name}.csv":
            return m
    return None


def read_raw(zip_path: Path, st_case: int):
    """The record's own rows in each member, with their CSV line numbers (line 1 = header).
    Returns (found, None) or (None, reason) when the zip cannot be read."""
    found: dict[str, tuple] = {}
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        return None, f"{zip_path.name} is not a readable zip ({e})"
    with zf:
        for member in MEMBERS:
            name = find_member(zf, member)
            if name is None:
                return None, f"member {member}.csv not found in {zip_path.name}"
            raw = zf.read(name)
            for enc in ("utf-8", "cp1252"):
                try:
                    text = raw.decode(enc).lstrip("\ufeff")
                    break
                except UnicodeDecodeError:
                    continue
            rows = csv.reader(io.StringIO(text))
            header = [h.strip().upper() for h in next(rows)]
            idx = {h: i for i, h in enumerate(header)}
            if "STATE" not in idx or "ST_CASE" not in idx:
                return None, f"{member}.csv in {zip_path.name} has no STATE/ST_CASE column"
            hits = []
            for line_no, row in enumerate(rows, start=2):
                if not row or len(row) < len(header):
                    continue
                if row[idx["STATE"]].strip() == "12" and row[idx["ST_CASE"]].strip() == str(st_case):
                    hits.append((line_no, {c: row[idx[c]].strip() for c in RAW_COLS[member] if c in idx}))
            found[member] = (Path(name).name, enc, hits)
    return found, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pick", choices=["normal", "edge"], help="let the tool choose a fitting record")
    ap.add_argument("--year", type=int)
    ap.add_argument("--st-case", type=int)
    ap.add_argument("--per-no", type=int, help="trace one death of a multi-victim crash only")
    ap.add_argument("--raw-dir", help="folder with the raw zips, to quote the source lines (optional)")
    ap.add_argument("--redact", action="store_true", help="mask case numbers in the output")
    ap.add_argument("--dsn", help="libpq connection string (default: PG* environment variables, database ped_safety)")
    args = ap.parse_args()
    conninfo = args.dsn or ("" if os.environ.get("PGDATABASE") else "dbname=ped_safety")
    conn = psycopg.connect(conninfo)
    global REDACT
    REDACT = R = args.redact
    if args.pick and (args.year is not None or args.st_case is not None):
        ap.error("--pick and --year/--st-case are mutually exclusive")

    if args.pick:
        year, st_case, why = pick(conn, args.pick)
    elif args.year is not None and args.st_case is not None:
        year, st_case, why = args.year, args.st_case, "chosen by the caller"
        if q1(conn, "SELECT 1 FROM crash WHERE (year, st_case) = (%s, %s)", year, st_case) is None:
            die(f"crash ({year}, {st_case}) is not in the database")
    else:
        ap.error("either --pick, or --year with --st-case")

    out(f"TRACE of crash ({year}, {st_case}) and its pedestrian fatality record(s)", R)
    out(f"why this record: {why}", R)
    out("read-only: this tool only SELECTs and reads the zip; it changes nothing", R)

    # 1 lineage ------------------------------------------------------------
    out("\n== 1  LINEAGE: which run loaded it, from which file =================", R)
    run = q1(conn, "SELECT run_id, started_at, finished_at, git_commit FROM etl_run "
                   "WHERE status = 'succeeded' ORDER BY run_id DESC LIMIT 1")
    if run is None:
        die("no succeeded pipeline run in this database: it was not loaded by pipeline/etl.py "
            "(is PGDATABASE pointing at the right database? the scenario load lives in ped_safety_week7)")
    src = q1(conn, "SELECT file_name, sha256, release, url, retrieved_on FROM source_file "
                   "WHERE run_id = %s AND data_year = %s", run[0], year)
    if src is None:
        die(f"run {run[0]} has no source_file row for year {year}: this database was not loaded by "
            "pipeline/etl.py (is PGDATABASE pointing at the right database?)")
    out(f"loaded by run {run[0]}: the latest succeeded run, and the load replaces every year, "
        f"so the current rows are its rows (finished {run[2]:%Y-%m-%d %H:%M:%S%z}; code commit {run[3][:7]})", R)
    out(f"source file: {src[0]}  sha256 {src[1][:12]}...  release '{src[2]}'  retrieved {src[4]}", R)
    g1 = q1(conn, "SELECT passed FROM validation_result WHERE run_id = %s AND check_name = %s",
            run[0], f"G1 sha256 {src[0]}")
    if g1 and g1[0]:
        out("gate G1 of that run verified this file's SHA-256 against the pinned manifest before reading it", R)

    # 2 raw ---------------------------------------------------------------
    raw = None
    out("\n== 2  RAW: the record's own lines inside the zip =====================", R)
    raw_dir = Path(args.raw_dir) if args.raw_dir else None
    zip_path = raw_dir / src[0] if raw_dir else None
    reason = None if zip_path and zip_path.exists() else "--raw-dir not given or file missing"
    if reason is None:
        raw, reason = read_raw(zip_path, st_case)
    if raw is not None:
        for member in MEMBERS:
            name, enc, hits = raw[member]
            for line_no, vals in hits:
                out(f"{name} (encoding {enc}) line {line_no}:", R)
                out("    " + "  ".join(f"{k}={v}" for k, v in vals.items()), R)
            if not hits:
                out(f"{name}: no row for this case (case not present in this member)", R)
    else:
        out(f"raw zip not readable here ({reason}): the stored values below come from the", R)
        out("database; run with --raw-dir pointing at the zips to quote the source CSV lines", R)

    # 3 transform ----------------------------------------------------------
    out("\n== 3  TRANSFORM: each cleaning rule next to its effect here ==========", R)
    crash = dict(zip(cols_of(conn, "crash"), q1(conn, "SELECT * FROM crash WHERE (year, st_case) = (%s, %s)", year, st_case)))
    peds = [dict(zip(cols_of(conn, "pedestrian"), r)) for r in
            qall(conn, "SELECT * FROM pedestrian WHERE (year, st_case) = (%s, %s) ORDER BY per_no", year, st_case)]
    kept = len(peds)
    if args.per_no is not None:
        peds = [p for p in peds if p["per_no"] == args.per_no]
        if not peds:
            die(f"crash ({year}, {st_case}) has no pedestrian row with per_no {args.per_no}; "
                f"stored per_no values: {[p for (p,) in qall(conn, 'SELECT per_no FROM pedestrian WHERE (year, st_case) = (%s, %s) ORDER BY per_no', year, st_case)]}")
    vehs = [dict(zip(cols_of(conn, "vehicle"), r)) for r in
            qall(conn, "SELECT * FROM vehicle WHERE (year, st_case) = (%s, %s) ORDER BY veh_no", year, st_case)]
    raw_person_rows = len(raw["person"][2]) if raw else None
    raw_acc = raw["accident"][2][0][1] if raw and raw["accident"][2] else None
    out(f"unit of observation: PER_TYP = 5 and INJ_SEV = 4 kept "
        f"{kept} death(s)" + (f" out of {raw_person_rows} person row(s) of this crash"
                              if raw_person_rows is not None else "") + " (cleaning plan, section 1.3)"
        + (f"; showing per_no {args.per_no} only" if args.per_no is not None else ""), R)
    if raw_acc:
        lat_raw, lon_raw = raw_acc.get("LATITUDE", ""), raw_acc.get("LONGITUD", "")
        filler = any(lat_raw.startswith(f) for f in LAT_FILLERS) or any(lon_raw.startswith(f) for f in LON_FILLERS)
        out(f"coordinates: raw LATITUDE={lat_raw} LONGITUD={lon_raw} -> stored "
            f"{'NULL' if crash['latitude'] is None else crash['latitude']} / {'NULL' if crash['longitud'] is None else crash['longitud']}"
            + ("  (FARS filler pair = 'no usable point' -> NULL; issue 5 rule a)" if filler else "  (inside the Florida box, kept)"), R)
    else:
        out(f"coordinates stored: {'NULL' if crash['latitude'] is None else crash['latitude']} / {'NULL' if crash['longitud'] is None else crash['longitud']}"
            + ("  (NULL = the raw file had a FARS filler pair; issue 5 rule a)" if crash["latitude"] is None else ""), R)
    for p in peds:
        out(f"striking vehicle of per_no {p['per_no']}: stored str_veh = {p['str_veh']}"
            + ("  (NULL would mean STR_VEH 0 or unresolved; rule 2 keeps the death either way)"
               if p["str_veh"] is not None else "  (STR_VEH 0 or unresolved -> NULL; rule 2: the death is kept)"), R)
    county_name = q1(conn, "SELECT name FROM county WHERE county_fips = %s", crash["county"])[0]
    out(f"county: code {crash['county']} -> foreign key to county '{county_name}' (business rule 3: mandatory, one of the 67)", R)
    out(f"unknown codes stay as values (issue 1): nothing in this record was imputed or dropped", R)

    # 4 database -----------------------------------------------------------
    out("\n== 4  DATABASE: the stored rows ======================================", R)
    show = lambda d: "  ".join(f"{k}={'NULL' if v is None else v}" for k, v in d.items())
    out(f"crash ({year}, {st_case}):  " + show({k: v for k, v in crash.items() if k not in ('year', 'st_case')}), R)
    for v in vehs:
        out(f"vehicle veh_no {v['veh_no']}:  " + show({k: x for k, x in v.items() if k not in ('year', 'st_case', 'veh_no')}), R)
    for p in peds:
        out(f"pedestrian per_no {p['per_no']}:  " + show({k: x for k, x in p.items() if k not in ('year', 'st_case', 'veh_no', 'per_no')}), R)
        t = q1(conn, "SELECT pbcwalk, pbswalk, pedloc, pedpos, pedctype FROM ped_crash_type "
                     "WHERE (year, st_case, per_no) = (%s, %s, %s)", year, st_case, p["per_no"])
        out(f"ped_crash_type per_no {p['per_no']}:  pbcwalk={t[0]}  pbswalk={t[1]}  pedloc={t[2]}  pedpos={t[3]}  pedctype={t[4]}"
            if t else f"ped_crash_type per_no {p['per_no']}: no row (allowed; v_dq_missing_typing reports it)", R)
    out("guarded by: composite PK (year, st_case, ...), the striking-vehicle FK into the same crash,", R)
    out("the county FK, the CHECK code lists, and the deferred 'one pedestrian + one vehicle' triggers", R)

    # 5 view ---------------------------------------------------------------
    out("\n== 5  VIEW v_ped_transactions: the items this death contributes ======", R)
    in_scope = crash["rur_urb"] == 2 and crash["func_sys"] not in (1, 2)
    for p in peds:
        row = q1(conn, "SELECT * FROM v_ped_transactions WHERE (year, st_case, per_no) = (%s, %s, %s)",
                 year, st_case, p["per_no"])
        if row:
            vcols = cols_of(conn, "v_ped_transactions")
            d = dict(zip(vcols, row))
            for k in ("year", "st_case", "per_no"):
                d.pop(k, None)
            out(f"per_no {p['per_no']} is IN the analysis view; its items:", R)
            for k, v in d.items():
                out(f"    {k:<18} = {v}", R)
        else:
            out(f"per_no {p['per_no']} is NOT in the view: scope filter rur_urb={crash['rur_urb']}, "
                f"func_sys={crash['func_sys']} (the view keeps urban crashes, rur_urb 2, off the "
                f"freeways, func_sys not 1-2); the death still counts in the county rate below", R)
    if in_scope and crash["geoid10"] is None:
        out("walkability reads 'unknown': no block group yet (EPA join pending" +
            (", and this crash has no point anyway)" if crash["latitude"] is None else ")"), R)

    # 6 aggregates ----------------------------------------------------------
    out("\n== 6  AGGREGATES: where the death is counted =========================", R)
    rate = q1(conn, "SELECT deaths_all, deaths_in_scope, person_years, rate_per_100k_per_year, unstable_rate "
                    "FROM v_county_rate WHERE county_fips = %s", crash["county"])
    out(f"v_county_rate '{county_name}': deaths_all={rate[0]} (this record among them), in_scope={rate[1]}, "
        f"person_years={rate[2]}, rate={rate[3]}/100k/yr, unstable={rate[4]}", R)
    n_checks = q1(conn, "SELECT count(*) FILTER (WHERE passed) FROM validation_result WHERE run_id = %s", run[0])[0]
    if n_checks:
        out(f"the load that carried this record passed {n_checks} check(s) (gates G1-G6) before COMMIT; "
            f"run {run[0]} details: python pipeline/etl.py status --run {run[0]}", R)
    out("\nend of trace", R)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
