#!/usr/bin/env python3
"""Check the sample records in samples/ against the business rules of the
conceptual data model (README.md, section 3).

Standard library only, so it runs anywhere:

    python tests/check_samples.py            # check the five sample records
    python tests/check_samples.py --negative # add three deliberately broken
                                             # rows and show the rules firing

Exit code 0 means every rule held (or, with --negative, that every injected
violation was caught).
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
YEARS = range(2020, 2025)


def load(name: str) -> list[dict[str, str]]:
    with open(SAMPLES / f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def key(row: dict[str, str], *cols: str) -> tuple[str, ...]:
    return tuple(row[c] for c in cols)


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def check(self, ok: bool, message: str) -> None:
        print(("  PASS  " if ok else "  FAIL  ") + message)
        if not ok:
            self.failures.append(message)

    def note(self, message: str) -> None:
        print("  note  " + message)
        self.notes.append(message)


def run(tables: dict[str, list[dict[str, str]]]) -> Report:
    r = Report()
    crash, vehicle, ped, ptype = (tables[t] for t in ("crash", "vehicle", "pedestrian", "ped_crash_type"))
    county, pop, bg = (tables[t] for t in ("county", "county_population", "block_group"))

    crash_keys = Counter(key(c, "year", "st_case") for c in crash)
    vehicle_keys = Counter(key(v, "year", "st_case", "veh_no") for v in vehicle)
    ped_keys = Counter(key(p, "year", "st_case", "veh_no", "per_no") for p in ped)
    ptype_keys = Counter(key(t, "year", "st_case", "veh_no", "per_no") for t in ptype)
    county_ids = {c["county_fips"] for c in county}
    pop_keys = {key(p, "county_fips", "year") for p in pop}
    bg_ids = {b["geoid10"]: b for b in bg}

    print("Identifiers")
    for name, keys in (("crash", crash_keys), ("vehicle", vehicle_keys),
                       ("pedestrian", ped_keys), ("ped_crash_type", ptype_keys)):
        dups = [k for k, n in keys.items() if n > 1]
        r.check(not dups, f"{name}: composite key is unique" + (f" (duplicates: {dups})" if dups else ""))
    by_case = defaultdict(set)
    for year, st_case in crash_keys:
        by_case[st_case].add(year)
    reused = {s: sorted(y) for s, y in by_case.items() if len(y) > 1}
    if reused:
        r.note(f"st_case reused across years, distinct crashes only because year is in the key: {reused}")

    print("Rule 1 - one crash, identified by year + st_case, for every dependent record")
    for name, rows in (("vehicle", vehicle), ("pedestrian", ped), ("ped_crash_type", ptype)):
        orphans = [key(x, "year", "st_case") for x in rows if key(x, "year", "st_case") not in crash_keys]
        r.check(not orphans, f"every {name} row belongs to an existing crash" + (f" (orphans: {orphans})" if orphans else ""))
    orphan_types = [k for k in ptype_keys if k not in ped_keys]
    r.check(not orphan_types, "every ped_crash_type row belongs to an existing pedestrian"
            + (f" (orphans: {orphan_types})" if orphan_types else ""))
    r.check(all(n == 1 for n in ptype_keys.values()), "at most one ped_crash_type row per pedestrian")

    print("Rule 2 - at most one striking vehicle, and it must be an in-transport vehicle of the same crash")
    bad = []
    for p in ped:
        if p["str_veh"] not in ("", "0"):
            if key(p, "year", "st_case") + (p["str_veh"],) not in vehicle_keys:
                bad.append(key(p, "year", "st_case", "per_no") + (p["str_veh"],))
    r.check(not bad, "str_veh is empty/0 or points to a vehicle in the same crash" + (f" (bad: {bad})" if bad else ""))
    r.check(all(p["veh_no"] == "0" and p["per_typ"] == "5" and p["inj_sev"] == "4" for p in ped),
            "pedestrian rows are non-motorists (veh_no 0) coded pedestrian (5) and fatal (4)")
    veh_per_crash = Counter(key(v, "year", "st_case") for v in vehicle)
    ped_per_crash = Counter(key(p, "year", "st_case") for p in ped)
    r.check(all(veh_per_crash[k] >= 1 for k in crash_keys), "every crash has at least one in-transport vehicle")
    r.check(all(ped_per_crash[k] >= 1 for k in crash_keys), "every crash has at least one pedestrian fatality")
    multi = {k: n for k, n in ped_per_crash.items() if n > 1}
    if multi:
        r.note(f"crashes with more than one pedestrian fatality (each death is its own row/transaction): {multi}")
    no_link = [key(p, "year", "st_case", "per_no") for p in ped if p["str_veh"] in ("", "0")]
    if no_link:
        r.note(f"pedestrians with no striking-vehicle link (allowed, vehicle items become 'unknown'): {no_link}")

    print("Rule 3 - county is mandatory and known; block group is optional and only with valid coordinates")
    bad_county = [key(c, "year", "st_case") + (c["county"],) for c in crash if c["county"] not in county_ids]
    r.check(not bad_county, "every crash has a county that exists in the county table" + (f" (bad: {bad_county})" if bad_county else ""))
    bad_geo = []
    for c in crash:
        has_point = bool(c["latitude"]) and bool(c["longitud"])
        has_bg = bool(c["geoid10"])
        if has_bg and not has_point:
            bad_geo.append((key(c, "year", "st_case"), "block group without coordinates"))
        if has_bg and c["geoid10"] not in bg_ids:
            bad_geo.append((key(c, "year", "st_case"), "unknown block group"))
    r.check(not bad_geo, "a block group is present only with valid coordinates and exists in block_group" + (f" (bad: {bad_geo})" if bad_geo else ""))
    mismatch = [key(c, "year", "st_case") for c in crash if c["geoid10"] and bg_ids.get(c["geoid10"], {}).get("county_fips") != c["county"]]
    if mismatch:
        r.note(f"warning: geocoded block group lies in a different county than the coded county: {mismatch}")
    missing_pop = [(cid, y) for cid in county_ids for y in YEARS if (cid, str(y)) not in pop_keys]
    r.check(not missing_pop, "every county has a population estimate for every year 2020-2024" + (f" (missing: {missing_pop})" if missing_pop else ""))
    bad_bg_county = [b["geoid10"] for b in bg if b["county_fips"] not in county_ids or b["geoid10"][2:5].lstrip("0") != b["county_fips"]]
    r.check(not bad_bg_county, "every block group belongs to an existing county and its geoid encodes that county" + (f" (bad: {bad_bg_county})" if bad_bg_county else ""))
    no_bg = [key(c, "year", "st_case") for c in crash if not c["geoid10"]]
    if no_bg:
        r.note(f"crashes with no block group (kept; they still count in county rates): {no_bg}")
    crash_counties = {c["county"] for c in crash}
    idle = sorted(county_ids - crash_counties, key=int)
    if idle:
        r.note(f"counties with zero sample crashes (allowed; rate = 0 with an unstable flag): {idle}")

    print("Unknown codes kept as values, not dropped")
    unknowns = []
    unknowns += [f"vehicle {key(v, 'year', 'st_case', 'veh_no')} body_typ=99" for v in vehicle if v["body_typ"] == "99"]
    unknowns += [f"vehicle {key(v, 'year', 'st_case', 'veh_no')} vspd_lim={v['vspd_lim']}" for v in vehicle if v["vspd_lim"] in ("98", "99")]
    unknowns += [f"pedestrian {key(p, 'year', 'st_case', 'per_no')} drinking={p['drinking']}" for p in ped if p["drinking"] in ("8", "9")]
    unknowns += [f"block_group {b['geoid10']} d4a=-99999 (no transit; treat as NULL)" for b in bg if b["d4a"] == "-99999"]
    for u in unknowns:
        r.note(u)
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--negative", action="store_true", help="inject broken rows and expect the rules to fail")
    args = ap.parse_args()

    tables = {t: load(t) for t in ("crash", "vehicle", "pedestrian", "ped_crash_type", "county", "county_population", "block_group")}
    if args.negative:
        print("Negative control: three rows that break one rule each are added in memory (nothing is written).\n")
        tables["vehicle"].append({"year": "2020", "st_case": "120001", "veh_no": "1", "body_typ": "4", "vspd_lim": "35", "hit_run": "0"})  # rule 1
        tables["pedestrian"].append({"year": "2022", "st_case": "121307", "veh_no": "0", "per_no": "2", "str_veh": "2",
                                     "per_typ": "5", "inj_sev": "4", "age": "40", "sex": "1", "drinking": "0"})  # rule 2
        tables["crash"].append({"year": "2023", "st_case": "120999", "county": "999", "geoid10": "", "month": "5", "day_week": "2",
                                "hour": "14", "rur_urb": "2", "func_sys": "4", "reljct2": "2", "lgt_cond": "1", "weather": "1",
                                "latitude": "", "longitud": "", "tway_id": "", "fatals": "1", "peds": "1"})  # rule 3
    report = run(tables)
    print()
    if args.negative:
        expected = 4  # rule 1 (orphan vehicle), rule 2 (bad str_veh), rule 3 (county 999), plus the new crash has no vehicle/pedestrian
        caught = len(report.failures)
        print(f"{caught} rule violations reported for the injected rows (expected at least {expected}).")
        return 0 if caught >= expected else 1
    if report.failures:
        print(f"{len(report.failures)} rule(s) failed.")
        return 1
    print("All rules hold for the five sample records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
