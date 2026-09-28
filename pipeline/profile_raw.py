#!/usr/bin/env python3
"""
profile_raw.py - Week 6 data profile of the raw sources, before any cleaning.

Reads the FARS National CSV zips (2020-2024) and the Census county file straight
from data/raw/ (nothing is extracted or modified) and writes measured evidence to
docs/profile/. Every number in docs/Week6_Data_Cleaning_Plan_Shkirpan.md comes
from these outputs, so the plan can be re-derived with one command:

    python pipeline/profile_raw.py

Inputs (see data/raw/MANIFEST.csv for checksums and retrieval dates):
    data/raw/FARS{year}NationalCSV.zip      year = 2020 ... 2024
    data/raw/co-est2025-alldata.csv         Census Vintage 2025 county estimates

Outputs:
    docs/profile/*.csv                      the tables cited in the plan
    docs/profile/PROFILE.md                 human-readable summary of the same tables
    docs/evidence/06_profile_run.log        run log (row counts per step)

The script never changes a value. It only counts. Codes such as 98/99 are counted as
"coded unknown", separately from empty cells, because in FARS they are values with a
documented meaning (FARS Analytical User's Manual), not missing data in the pandas sense.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "profile"
EVID = ROOT / "docs" / "evidence"
YEARS = [2020, 2021, 2022, 2023, 2024]
FL = 12  # FARS state code for Florida

# FARS files the project loads (lower-case names; the zips vary in case)
FILES = ["accident", "vehicle", "person", "pbtype", "parkwork"]

# ---------------------------------------------------------------------------
# Variable dictionary: type per Tan & Steinbach (2019, section 2.1), unknown codes
# per the FARS Analytical User's Manual. "unknown" lists codes that carry no
# information about the attribute itself (not reported / unknown / not applicable).
# ---------------------------------------------------------------------------
VARS = OrderedDict([
    # accident
    ("accident.ST_CASE",  dict(kind="nominal (key)",   unknown=[])),
    ("accident.COUNTY",   dict(kind="nominal",          unknown=[0, 997, 998, 999])),
    ("accident.MONTH",    dict(kind="ordinal (cyclic)", unknown=[])),
    ("accident.DAY_WEEK", dict(kind="ordinal (cyclic)", unknown=[])),
    ("accident.HOUR",     dict(kind="ordinal (cyclic)", unknown=[99])),
    ("accident.RUR_URB",  dict(kind="nominal",          unknown=[6, 8, 9])),
    ("accident.FUNC_SYS", dict(kind="ordinal",          unknown=[96, 98, 99])),
    ("accident.RELJCT2",  dict(kind="nominal",          unknown=[98, 99])),
    ("accident.LGT_COND", dict(kind="nominal",          unknown=[6, 7, 8, 9])),
    ("accident.WEATHER",  dict(kind="nominal",          unknown=[8, 98, 99])),
    ("accident.LATITUDE", dict(kind="interval (ratio-like coordinate)", unknown=[77.7777, 88.8888, 99.9999])),
    ("accident.LONGITUD", dict(kind="interval (ratio-like coordinate)", unknown=[777.7777, 888.8888, 999.9999])),
    ("accident.TWAY_ID",  dict(kind="nominal (free text)", unknown=[])),
    ("accident.FATALS",   dict(kind="ratio (count)",    unknown=[])),
    ("accident.PEDS",     dict(kind="ratio (count)",    unknown=[])),
    # vehicle
    ("vehicle.VEH_NO",    dict(kind="nominal (key)",   unknown=[])),
    ("vehicle.BODY_TYP",  dict(kind="nominal",          unknown=[98, 99])),
    ("vehicle.VSPD_LIM",  dict(kind="ratio (mph)",      unknown=[98, 99])),
    ("vehicle.HIT_RUN",   dict(kind="nominal (binary)", unknown=[9])),
    # person
    ("person.PER_NO",     dict(kind="nominal (key)",   unknown=[])),
    ("person.STR_VEH",    dict(kind="nominal (link)",  unknown=[0])),
    ("person.PER_TYP",    dict(kind="nominal",          unknown=[])),
    ("person.INJ_SEV",    dict(kind="ordinal",          unknown=[9])),
    ("person.AGE",        dict(kind="ratio (years)",    unknown=[998, 999])),
    ("person.SEX",        dict(kind="nominal",          unknown=[8, 9])),
    ("person.DRINKING",   dict(kind="nominal",          unknown=[8, 9])),
    # pbtype
    ("pbtype.PBCWALK",    dict(kind="nominal (binary)", unknown=[9])),
    ("pbtype.PBSWALK",    dict(kind="nominal (binary)", unknown=[9])),
    ("pbtype.PEDLOC",     dict(kind="nominal",          unknown=[9])),
    ("pbtype.PEDPOS",     dict(kind="nominal",          unknown=[9])),
    ("pbtype.PEDCTYPE",   dict(kind="nominal",          unknown=[900, 910, 990])),
    ("pbtype.PEDCGP",     dict(kind="nominal",          unknown=[990])),
])

FREQ_VARS = [
    "accident.RUR_URB", "accident.FUNC_SYS", "accident.LGT_COND", "accident.RELJCT2",
    "accident.WEATHER", "accident.HOUR", "accident.DAY_WEEK", "accident.COUNTY",
    "vehicle.VSPD_LIM", "vehicle.BODY_TYP", "vehicle.HIT_RUN",
    "person.STR_VEH", "person.SEX", "person.DRINKING", "person.AGE",
    "pbtype.PBCWALK", "pbtype.PBSWALK", "pbtype.PEDLOC", "pbtype.PEDPOS", "pbtype.PEDCGP",
]

LOG: list[str] = []


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  {msg}"
    LOG.append(line)
    print(line, flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_member(zf: zipfile.ZipFile, member: str) -> pd.DataFrame:
    """Read one CSV from the zip as text (dtype=str) so nothing is coerced silently."""
    raw = zf.read(member)
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, low_memory=False)
    df.columns = [c.strip().upper() for c in df.columns]
    df.attrs["encoding"] = enc
    return df


def find_member(zf: zipfile.ZipFile, name: str) -> str | None:
    for m in zf.namelist():
        base = Path(m).name.lower()
        if base == f"{name}.csv":
            return m
    return None


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.strip(), errors="coerce")


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else float("nan")


# ---------------------------------------------------------------------------
# 1. Inventory, checksums, row counts
# ---------------------------------------------------------------------------
def load_all() -> tuple[dict, list, list]:
    """Returns {year: {file: DataFrame(Florida rows)}}, inventory rows, manifest rows."""
    data: dict[int, dict[str, pd.DataFrame]] = {}
    inventory, manifest = [], []
    for y in YEARS:
        zpath = RAW / f"FARS{y}NationalCSV.zip"
        if not zpath.exists():
            log(f"MISSING {zpath.name}")
            continue
        digest = sha256(zpath)
        manifest.append(dict(source="FARS", data_year=y, file_name=zpath.name,
                             url=f"https://static.nhtsa.gov/nhtsa/downloads/FARS/{y}/National/{zpath.name}",
                             bytes=zpath.stat().st_size, sha256=digest))
        data[y] = {}
        with zipfile.ZipFile(zpath) as zf:
            members = zf.namelist()
            inventory.append(dict(year=y, file="(zip)", member_count=len(members),
                                  national_rows="", florida_rows="", columns="", encoding=""))
            for name in FILES:
                m = find_member(zf, name)
                if m is None:
                    inventory.append(dict(year=y, file=name, member_count="", national_rows="absent",
                                          florida_rows="", columns="", encoding=""))
                    continue
                df = read_csv_member(zf, m)
                state_col = "STATE" if "STATE" in df.columns else None
                if state_col is None:
                    fl = df
                else:
                    fl = df[to_num(df[state_col]) == FL].copy()
                fl.reset_index(drop=True, inplace=True)
                data[y][name] = fl
                inventory.append(dict(year=y, file=name, member_count="", national_rows=len(df),
                                      florida_rows=len(fl), columns=df.shape[1],
                                      encoding=df.attrs.get("encoding", "")))
                log(f"{y} {name:9s} national={len(df):>7,} florida={len(fl):>6,} cols={df.shape[1]}")
    census = RAW / "co-est2025-alldata.csv"
    if census.exists():
        manifest.append(dict(source="CENSUS_POPEST", data_year="", file_name=census.name,
                             url="https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv",
                             bytes=census.stat().st_size, sha256=sha256(census)))
    return data, inventory, manifest


# ---------------------------------------------------------------------------
# 2. Column drift across years (schema stability)
# ---------------------------------------------------------------------------
def column_drift(data: dict) -> pd.DataFrame:
    rows = []
    for name in FILES:
        cols_by_year = {y: set(data[y][name].columns) for y in data if name in data[y]}
        if not cols_by_year:
            continue
        union = set().union(*cols_by_year.values())
        for c in sorted(union):
            present = [y for y in cols_by_year if c in cols_by_year[y]]
            if len(present) != len(cols_by_year):
                rows.append(dict(file=name, column=c, present_in=" ".join(map(str, present)),
                                 absent_in=" ".join(str(y) for y in cols_by_year if y not in present)))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Unit of observation: Florida pedestrian fatalities per year
# ---------------------------------------------------------------------------
def unit_counts(data: dict) -> pd.DataFrame:
    rows = []
    for y, d in data.items():
        p = d["person"]
        per_typ, inj = to_num(p["PER_TYP"]), to_num(p["INJ_SEV"])
        ped_fatal = p[(per_typ == 5) & (inj == 4)]
        crashes_with_ped_death = ped_fatal["ST_CASE"].nunique()
        a = d["accident"].set_index("ST_CASE")
        ru = to_num(a["RUR_URB"]).reindex(ped_fatal["ST_CASE"]).values
        fs = to_num(a["FUNC_SYS"]).reindex(ped_fatal["ST_CASE"]).values
        rows.append(dict(
            year=y,
            fl_crashes=len(d["accident"]),
            fl_fatalities_all=int((inj == 4).sum()),
            fl_person_rows=len(p),
            fl_nonmotorist_rows=int((to_num(p["VEH_NO"]) == 0).sum()),
            fl_pedestrian_rows_any_injury=int((per_typ == 5).sum()),
            fl_pedestrian_fatalities=len(ped_fatal),
            crashes_with_ped_fatality=crashes_with_ped_death,
            ped_fatalities_per_crash_max=int(ped_fatal.groupby("ST_CASE").size().max()) if len(ped_fatal) else 0,
            crashes_with_2plus_ped_fatalities=int((ped_fatal.groupby("ST_CASE").size() >= 2).sum()),
            ped_fatalities_urban=int((ru == 2).sum()),
            ped_fatalities_rural=int((ru == 1).sum()),
            ped_fatalities_rur_urb_unknown=int(np.isin(ru, [6, 8, 9]).sum()),
            ped_fatalities_urban_nonfreeway_subset=int(((ru == 2) & np.isin(fs, [3, 4, 5, 6, 7])).sum()),
            ped_fatalities_urban_freeway=int(((ru == 2) & np.isin(fs, [1, 2])).sum()),
            ped_fatalities_urban_func_sys_unknown=int(((ru == 2) & np.isin(fs, [96, 98, 99])).sum()),
        ))
    df = pd.DataFrame(rows)
    total = df.drop(columns="year").sum(numeric_only=True)
    total["year"] = "total"
    return pd.concat([df, total.to_frame().T], ignore_index=True)


# ---------------------------------------------------------------------------
# 4. Type / range / missingness profile of the in-scope variables
# ---------------------------------------------------------------------------
def variable_profile(data: dict, ped_keys: dict) -> pd.DataFrame:
    rows = []
    for key, spec in VARS.items():
        fname, col = key.split(".")
        for y, d in data.items():
            if fname not in d or col not in d[fname].columns:
                rows.append(dict(variable=key, year=y, present=False))
                continue
            df = d[fname]
            # restrict person/pbtype to the unit of observation, vehicle to striking vehicles
            if fname == "person":
                df = df[ped_keys[y]["person_mask"]]
            elif fname == "pbtype":
                df = df[ped_keys[y]["pbtype_mask"]]
            elif fname == "vehicle":
                df = df[ped_keys[y]["vehicle_mask"]]
            elif fname == "accident":
                df = df[ped_keys[y]["accident_mask"]]
            s = df[col]
            n = len(s)
            blank = int((s.str.strip() == "").sum())
            num = to_num(s)
            nonnum = int(num.isna().sum() - blank)
            unk_codes = spec["unknown"]
            is_unk = num.isin(unk_codes) if unk_codes else pd.Series(False, index=s.index)
            valid = num[~is_unk & num.notna()]
            rows.append(dict(
                variable=key, year=y, present=True, kind=spec["kind"], rows=n,
                dtype_in_file="text" if col == "TWAY_ID" else ("numeric" if nonnum == 0 else "mixed"),
                blank_cells=blank, blank_pct=pct(blank, n),
                coded_unknown=int(is_unk.sum()), coded_unknown_pct=pct(int(is_unk.sum()), n),
                unknown_codes=" ".join(str(c) for c in unk_codes),
                distinct_values=int(s.nunique()),
                min_valid=(None if valid.empty else float(valid.min())),
                max_valid=(None if valid.empty else float(valid.max())),
                median_valid=(None if valid.empty else float(valid.median())),
            ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. Keys, duplicates, and cross-file consistency
# ---------------------------------------------------------------------------
def key_checks(data: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, reuse = [], {}
    COUNT_CHECKS = ("STR_VEH", "no pbtype row")
    for y, d in data.items():
        a, v, p, b = d["accident"], d["vehicle"], d["person"], d["pbtype"]
        pw = d.get("parkwork", pd.DataFrame(columns=["ST_CASE", "VEH_NO"]))
        rows.append(dict(year=y, check="accident: ST_CASE unique", n=len(a), violations=int(a["ST_CASE"].duplicated().sum())))
        rows.append(dict(year=y, check="accident: exact duplicate rows", n=len(a), violations=int(a.duplicated().sum())))
        rows.append(dict(year=y, check="vehicle: (ST_CASE, VEH_NO) unique", n=len(v), violations=int(v.duplicated(["ST_CASE", "VEH_NO"]).sum())))
        rows.append(dict(year=y, check="person: (ST_CASE, VEH_NO, PER_NO) unique", n=len(p), violations=int(p.duplicated(["ST_CASE", "VEH_NO", "PER_NO"]).sum())))
        rows.append(dict(year=y, check="pbtype: (ST_CASE, VEH_NO, PER_NO) unique", n=len(b), violations=int(b.duplicated(["ST_CASE", "VEH_NO", "PER_NO"]).sum())))
        rows.append(dict(year=y, check="pbtype: exact duplicate rows", n=len(b), violations=int(b.duplicated().sum())))
        # orphans
        cases = set(a["ST_CASE"])
        rows.append(dict(year=y, check="vehicle rows whose ST_CASE is not in accident", n=len(v), violations=int((~v["ST_CASE"].isin(cases)).sum())))
        rows.append(dict(year=y, check="person rows whose ST_CASE is not in accident", n=len(p), violations=int((~p["ST_CASE"].isin(cases)).sum())))
        rows.append(dict(year=y, check="pbtype rows whose ST_CASE is not in accident", n=len(b), violations=int((~b["ST_CASE"].isin(cases)).sum())))
        pk = set(zip(p["ST_CASE"], p["VEH_NO"], p["PER_NO"]))
        bk = list(zip(b["ST_CASE"], b["VEH_NO"], b["PER_NO"]))
        rows.append(dict(year=y, check="pbtype rows with no matching person row", n=len(b), violations=sum(k not in pk for k in bk)))
        # pedestrian fatalities without a pbtype row
        per_typ, inj = to_num(p["PER_TYP"]), to_num(p["INJ_SEV"])
        ped = p[(per_typ == 5) & (inj == 4)]
        bk_set = set(bk)
        no_pb = sum(k not in bk_set for k in zip(ped["ST_CASE"], ped["VEH_NO"], ped["PER_NO"]))
        rows.append(dict(year=y, check="pedestrian fatalities with no pbtype row", n=len(ped), violations=int(no_pb)))
        # pbtype person type vs person file
        if "PBPTYPE" in b.columns:
            m = b.merge(p[["ST_CASE", "VEH_NO", "PER_NO", "PER_TYP"]], on=["ST_CASE", "VEH_NO", "PER_NO"], how="inner")
            rows.append(dict(year=y, check="pbtype PBPTYPE disagrees with person PER_TYP", n=len(m),
                             violations=int((to_num(m["PBPTYPE"]) != to_num(m["PER_TYP"])).sum())))
        # striking vehicle resolution
        vkeys = set(zip(v["ST_CASE"], v["VEH_NO"]))
        pwkeys = set(zip(pw["ST_CASE"], pw["VEH_NO"])) if len(pw) else set()
        sv = to_num(ped["STR_VEH"]).fillna(-1).astype(int)
        keys = list(zip(ped["ST_CASE"], sv.astype(str)))
        in_transport = sum((k in vkeys) for k in keys)
        zero = int((sv == 0).sum())
        in_park = sum((k in pwkeys) and (k not in vkeys) for k in keys)
        neither = len(ped) - in_transport - zero - in_park
        rows.append(dict(year=y, check="pedestrian fatalities: STR_VEH resolves to in-transport vehicle", n=len(ped), violations=int(in_transport)))
        rows.append(dict(year=y, check="pedestrian fatalities: STR_VEH = 0 (not applicable)", n=len(ped), violations=zero))
        rows.append(dict(year=y, check="pedestrian fatalities: STR_VEH resolves only to parked/working vehicle", n=len(ped), violations=int(in_park)))
        rows.append(dict(year=y, check="pedestrian fatalities: STR_VEH resolves to nothing", n=len(ped), violations=int(neither)))
        # FATALS reconciliation
        deaths = p[inj == 4].groupby("ST_CASE").size()
        fat = to_num(a.set_index("ST_CASE")["FATALS"])
        cmp = pd.concat([fat.rename("fatals"), deaths.rename("deaths")], axis=1).fillna(0)
        rows.append(dict(year=y, check="accident.FATALS != count of INJ_SEV=4 person rows", n=len(cmp), violations=int((cmp["fatals"] != cmp["deaths"]).sum())))
        nonmot = p[to_num(p["VEH_NO"]) == 0].groupby("ST_CASE").size()
        peds = to_num(a.set_index("ST_CASE")["PEDS"])
        cmp2 = pd.concat([peds.rename("peds"), nonmot.rename("nonmot")], axis=1).fillna(0)
        rows.append(dict(year=y, check="accident.PEDS != count of VEH_NO=0 person rows", n=len(cmp2), violations=int((cmp2["peds"] != cmp2["nonmot"]).sum())))
        # crashes with a pedestrian death: at least one in-transport vehicle?
        ped_cases = set(ped["ST_CASE"])
        rows.append(dict(year=y, check="crashes with a pedestrian death but no in-transport vehicle row", n=len(ped_cases),
                         violations=len(ped_cases - set(v["ST_CASE"]))))
        for c in a["ST_CASE"]:
            reuse.setdefault(c, []).append(y)
    reuse_df = pd.DataFrame([dict(st_case=c, years=" ".join(map(str, ys)), n_years=len(ys)) for c, ys in reuse.items()])
    out = pd.DataFrame(rows).rename(columns={"violations": "count"})
    out["kind"] = ["count (descriptive)" if any(k in c for k in COUNT_CHECKS) else "rule (should be 0)" for c in out["check"]]
    return out, reuse_df


# ---------------------------------------------------------------------------
# 6. Category frequencies (on the unit of observation)
# ---------------------------------------------------------------------------
def frequencies(data: dict, ped_keys: dict) -> pd.DataFrame:
    rows = []
    for key in FREQ_VARS:
        fname, col = key.split(".")
        for y, d in data.items():
            if fname not in d or col not in d[fname].columns:
                continue
            df = d[fname]
            mask = ped_keys[y][f"{fname}_mask"]
            s = df.loc[mask, col]
            label_col = col + "NAME"
            labels = df.loc[mask, label_col] if label_col in df.columns else None
            if col == "AGE":
                num = to_num(s)
                bins = pd.cut(num.where(num < 900), [-1, 14, 24, 44, 64, 200], labels=["0-14", "15-24", "25-44", "45-64", "65+"])
                s = bins.astype(str).where(num < 900, "998/999 unknown")
                labels = None
            if col == "HOUR":
                num = to_num(s)
                bins = pd.cut(num.where(num < 24), [-1, 5, 11, 17, 20, 23], labels=["00-05", "06-11", "12-17", "18-20", "21-23"])
                s = bins.astype(str).where(num < 24, "99 unknown")
                labels = None
            if col == "VSPD_LIM":
                num = to_num(s)
                bins = pd.cut(num.where(num < 98), [-1, 0, 30, 40, 50, 97], labels=["0 none", "5-30", "35-40", "45-50", "55+"])
                s = bins.astype(str).where(num < 98, num.astype("Int64").astype(str) + " unknown")
                labels = None
            if col == "COUNTY":
                pass
            vc = s.value_counts(dropna=False)
            for val, n in vc.items():
                lab = ""
                if labels is not None:
                    lab = labels[s == val].mode().iloc[0] if (s == val).any() else ""
                rows.append(dict(variable=key, year=y, value=val, label=lab, n=int(n), pct=pct(int(n), len(s))))
    df = pd.DataFrame(rows)
    # pooled 2020-2024
    pooled = df.groupby(["variable", "value"], as_index=False).agg(n=("n", "sum"), label=("label", "first"))
    tot = pooled.groupby("variable")["n"].transform("sum")
    pooled["pct"] = (100 * pooled["n"] / tot).round(2)
    pooled["year"] = "2020-2024"
    return pd.concat([df, pooled[df.columns]], ignore_index=True)


# ---------------------------------------------------------------------------
# 7. Code drift: values that appear in some years only
# ---------------------------------------------------------------------------
def code_drift(data: dict, ped_keys: dict) -> pd.DataFrame:
    rows = []
    for key in VARS:
        fname, col = key.split(".")
        if col in ("TWAY_ID", "LATITUDE", "LONGITUD", "ST_CASE", "VEH_NO", "PER_NO", "AGE",
                   "MONTH", "DAY_WEEK", "HOUR", "COUNTY", "FATALS", "PEDS", "PER_TYP", "INJ_SEV", "STR_VEH"):
            continue
        vals = {}
        for y, d in data.items():
            if fname in d and col in d[fname].columns:
                vals[y] = set(to_num(d[fname][col]).dropna().astype(int).unique())
        if not vals:
            continue
        union = set().union(*vals.values())
        for v in sorted(union):
            present = [y for y in vals if v in vals[y]]
            if len(present) != len(vals):
                rows.append(dict(variable=key, code=v, present_in=" ".join(map(str, present)),
                                 absent_in=" ".join(str(y) for y in vals if y not in present)))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 8. Coordinates and geography
# ---------------------------------------------------------------------------
def geo_profile(data: dict, ped_keys: dict) -> pd.DataFrame:
    rows = []
    for y, d in data.items():
        a = d["accident"][ped_keys[y]["accident_mask"]]
        lat, lon = to_num(a["LATITUDE"]), to_num(a["LONGITUD"])
        filler = lat.isin([77.7777, 88.8888, 99.9999]) | lon.isin([777.7777, 888.8888, 999.9999])
        in_box = (lat.between(24.3, 31.1) & lon.between(-87.7, -79.8))
        dec = a["LATITUDE"].str.strip().str.split(".").str[-1].str.len()
        county = to_num(a["COUNTY"])
        dup_points = a.loc[~filler, ["LATITUDE", "LONGITUD"]].duplicated(keep=False)
        rows.append(dict(
            year=y, crashes_with_ped_fatality=len(a),
            coord_filler_codes=int(filler.sum()), coord_filler_pct=pct(int(filler.sum()), len(a)),
            coord_outside_fl_bbox=int((~filler & ~in_box).sum()),
            coord_usable=int((~filler & in_box).sum()), coord_usable_pct=pct(int((~filler & in_box).sum()), len(a)),
            lat_decimals_min=int(dec.min()), lat_decimals_max=int(dec.max()),
            repeated_points=int(dup_points.sum()),
            county_codes_distinct=int(county.nunique()),
            county_unknown_codes=int(county.isin([0, 997, 998, 999]).sum()),
            county_out_of_range=int((~county.between(1, 133)).sum()),
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 8b. Structure of the missingness and internal consistency (Tan & Steinbach 2.2.1:
#     missing values, inconsistent values, noise). All on the unit of observation.
# ---------------------------------------------------------------------------
def structure_checks(data: dict, ped_keys: dict) -> pd.DataFrame:
    rows = []
    frames = []
    for y, d in data.items():
        p = d["person"][ped_keys[y]["person_mask"]].copy()
        a = d["accident"].set_index("ST_CASE")
        v = d["vehicle"].set_index(["ST_CASE", "VEH_NO"])
        b = d["pbtype"].set_index(["ST_CASE", "VEH_NO", "PER_NO"])
        p["year"] = y
        for c in ["HOUR", "LGT_COND", "RUR_URB", "FUNC_SYS", "MONTH", "COUNTY", "LATITUDE", "LONGITUD"]:
            p[c] = a[c].reindex(p["ST_CASE"]).values
        vk = list(zip(p["ST_CASE"], to_num(p["STR_VEH"]).astype(int).astype(str)))
        for c in ["VSPD_LIM", "BODY_TYP", "HIT_RUN"]:
            p[c] = v[c].reindex(vk).values
        bk = list(zip(p["ST_CASE"], p["VEH_NO"], p["PER_NO"]))
        for c in ["PEDCGP", "PEDCTYPE"]:
            p[c] = b[c].reindex(bk).values
        # number of in-transport vehicles in the crash and whether their speed limits agree
        vv = d["vehicle"].copy(); vv["VSPD_LIM_n"] = to_num(vv["VSPD_LIM"])
        g = vv.groupby("ST_CASE")["VSPD_LIM_n"].agg(["size", "nunique"])
        p["n_vehicles"] = g["size"].reindex(p["ST_CASE"]).values
        p["n_speed_values"] = g["nunique"].reindex(p["ST_CASE"]).values
        frames.append(p)
    u = pd.concat(frames, ignore_index=True)
    for c in ["HOUR", "LGT_COND", "RUR_URB", "FUNC_SYS", "MONTH", "VSPD_LIM", "BODY_TYP", "HIT_RUN", "PEDCGP", "PEDCTYPE", "DRINKING", "AGE", "SEX", "COUNTY"]:
        u[c] = to_num(u[c])
    N = len(u)
    def add(check, group, mask_group, mask_flag):
        n = int(mask_group.sum()); k = int((mask_group & mask_flag).sum())
        rows.append(dict(check=check, group=group, n=n, flagged=k, flagged_pct=pct(k, n)))
    unk_body = u["BODY_TYP"].isin([98, 99]); unk_spd = u["VSPD_LIM"].isin([98, 99])
    for hr, lab in [(0, "HIT_RUN = 0 (stayed)"), (1, "HIT_RUN = 1 (left the scene)")]:
        add("BODY_TYP unknown (98/99) by hit-and-run", lab, u["HIT_RUN"] == hr, unk_body)
        add("VSPD_LIM unknown (98/99) by hit-and-run", lab, u["HIT_RUN"] == hr, unk_spd)
    for y in YEARS:
        add("VSPD_LIM unknown (98/99) by year", str(y), u["year"] == y, unk_spd)
        add("DRINKING not reported/unknown (8/9) by year", str(y), u["year"] == y, u["DRINKING"].isin([8, 9]))
        add("RUR_URB not reported/unknown (6/8/9) by year", str(y), u["year"] == y, u["RUR_URB"].isin([6, 8, 9]))
        add("PEDCGP 990 (other/unknown, insufficient details) by year", str(y), u["year"] == y, u["PEDCGP"] == 990)
    # speed limit unknown by road class (is it random across the antecedent variable?)
    for fs, lab in [(3, "FUNC_SYS 3 principal arterial"), (4, "FUNC_SYS 4 minor arterial"), (5, "FUNC_SYS 5 major collector"), (6, "FUNC_SYS 6 minor collector"), (7, "FUNC_SYS 7 local"), (1, "FUNC_SYS 1 interstate"), (2, "FUNC_SYS 2 freeway/expressway")]:
        add("VSPD_LIM unknown (98/99) by road class", lab, u["FUNC_SYS"] == fs, unk_spd)
    # internal consistency: light condition vs hour
    night = u["HOUR"].isin([22, 23, 0, 1, 2, 3, 4]); midday = u["HOUR"].between(10, 15)
    add("LGT_COND = daylight (1) while HOUR is 22-04", "all deaths", pd.Series(True, index=u.index), (u["LGT_COND"] == 1) & night)
    add("LGT_COND = dark (2/3) while HOUR is 10-15", "all deaths", pd.Series(True, index=u.index), u["LGT_COND"].isin([2, 3]) & midday)
    # speed limit semantics
    add("VSPD_LIM = 0 (no statutory limit)", "all deaths", pd.Series(True, index=u.index), u["VSPD_LIM"] == 0)
    add("VSPD_LIM valid but not a multiple of 5", "all deaths", pd.Series(True, index=u.index), (u["VSPD_LIM"] < 98) & (u["VSPD_LIM"] % 5 != 0))
    multi = u["n_vehicles"] >= 2
    add("death in a crash with 2+ in-transport vehicles", "all deaths", pd.Series(True, index=u.index), multi)
    add("... and the vehicles report different VSPD_LIM values", "deaths in multi-vehicle crashes", multi, u["n_speed_values"] >= 2)
    # sparse categories
    for col in ["BODY_TYP", "PEDCTYPE", "PEDCGP"]:
        vc = u[col].value_counts()
        rows.append(dict(check=f"{col}: distinct codes / codes with < 1% support (< {int(0.01*N)} deaths)", group="2020-2024",
                         n=int(vc.size), flagged=int((vc < 0.01 * N).sum()), flagged_pct=pct(int((vc < 0.01 * N).sum()), int(vc.size))))
    # month distribution of the provisional 2024 file vs the four final years
    m24 = u[u.year == 2024]["MONTH"].value_counts(normalize=True).sort_index()
    mfin = u[u.year < 2024]["MONTH"].value_counts(normalize=True).sort_index()
    for m in range(1, 13):
        rows.append(dict(check="share of deaths by month: 2024 ARF vs 2020-2023 final", group=f"month {m:02d}",
                         n=round(100 * mfin.get(m, 0), 2), flagged=round(100 * m24.get(m, 0), 2), flagged_pct=round(100 * (m24.get(m, 0) - mfin.get(m, 0)), 2)))
    # county concentration
    cc = u["COUNTY"].value_counts()
    top10 = int(cc.head(10).sum())
    rows.append(dict(check="deaths in the 10 counties with most deaths", group="2020-2024", n=N, flagged=top10, flagged_pct=pct(top10, N)))
    rows.append(dict(check="counties with fewer than 20 deaths in five years", group="2020-2024", n=int(cc.size), flagged=int((cc < 20).sum()), flagged_pct=pct(int((cc < 20).sum()), int(cc.size))))
    # age / sex plausibility
    add("AGE reported as 0-4", "all deaths", pd.Series(True, index=u.index), u["AGE"].between(0, 4))
    add("AGE unknown (998/999)", "all deaths", pd.Series(True, index=u.index), u["AGE"].isin([998, 999]))
    add("SEX not reported/unknown (8/9)", "all deaths", pd.Series(True, index=u.index), u["SEX"].isin([8, 9]))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 9. Census county file
# ---------------------------------------------------------------------------
def census_profile(data: dict) -> pd.DataFrame:
    path = RAW / "co-est2025-alldata.csv"
    rows = []
    if not path.exists():
        return pd.DataFrame([dict(check="file present", value="no")])
    raw = path.read_bytes()
    enc = "utf-8"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        enc = "latin-1"
    df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
    rows.append(dict(check="encoding that decodes the file", value=enc))
    rows.append(dict(check="rows (all US)", value=len(df)))
    rows.append(dict(check="columns", value=df.shape[1]))
    fl = df[(df["STATE"] == "12")]
    rows.append(dict(check="Florida rows incl. state summary (SUMLEV 040)", value=len(fl)))
    flc = fl[fl["SUMLEV"] == "050"]
    rows.append(dict(check="Florida county rows (SUMLEV 050)", value=len(flc)))
    popcols = [c for c in df.columns if c.startswith("POPESTIMATE")]
    rows.append(dict(check="POPESTIMATE columns", value=" ".join(popcols)))
    rows.append(dict(check="Florida county codes are odd 1..133", value=bool(flc["COUNTY"].astype(int).between(1, 133).all() and (flc["COUNTY"].astype(int) % 2 == 1).all())))
    for c in popcols:
        v = pd.to_numeric(flc[c], errors="coerce")
        rows.append(dict(check=f"{c}: FL county total / min / max", value=f"{int(v.sum()):,} / {int(v.min()):,} / {int(v.max()):,}"))
    # FARS county codes used vs Census list
    fars_counties = set()
    for y, d in data.items():
        fars_counties |= set(to_num(d["accident"]["COUNTY"]).dropna().astype(int))
    census_counties = set(flc["COUNTY"].astype(int))
    rows.append(dict(check="FARS county codes (FL, all crashes) not in Census county list", value=sorted(fars_counties - census_counties)))
    rows.append(dict(check="Census counties with zero FARS crashes 2020-2024", value=sorted(census_counties - fars_counties)))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    log("profile_raw.py start")
    data, inventory, manifest = load_all()
    if not data:
        log("no FARS zips found in data/raw/ - nothing to profile")
        return 1
    pd.DataFrame(manifest).to_csv(OUT / "00_manifest_sha256.csv", index=False)
    pd.DataFrame(inventory).to_csv(OUT / "01_inventory.csv", index=False)

    # masks for the unit of observation
    ped_keys = {}
    for y, d in data.items():
        p = d["person"]
        pm = (to_num(p["PER_TYP"]) == 5) & (to_num(p["INJ_SEV"]) == 4)
        ped = p[pm]
        cases = set(ped["ST_CASE"])
        am = d["accident"]["ST_CASE"].isin(cases)
        b = d["pbtype"]
        bm = pd.Series(list(zip(b["ST_CASE"], b["VEH_NO"], b["PER_NO"]))).isin(set(zip(ped["ST_CASE"], ped["VEH_NO"], ped["PER_NO"]))).values
        v = d["vehicle"]
        sv = to_num(ped["STR_VEH"]).fillna(-1).astype(int).astype(str)
        vm = pd.Series(list(zip(v["ST_CASE"], v["VEH_NO"]))).isin(set(zip(ped["ST_CASE"], sv))).values
        ped_keys[y] = dict(person_mask=pm.values, accident_mask=am.values, pbtype_mask=bm, vehicle_mask=vm)

    unit = unit_counts(data);              unit.to_csv(OUT / "02_unit_of_observation.csv", index=False)
    drift = column_drift(data);            drift.to_csv(OUT / "03_column_drift.csv", index=False)
    prof = variable_profile(data, ped_keys); prof.to_csv(OUT / "04_variable_profile.csv", index=False)
    keys, reuse = key_checks(data);        keys.to_csv(OUT / "05_keys_duplicates_consistency.csv", index=False)
    # only the distribution is published: a list of real case numbers does not belong in the repository
    reuse.groupby("n_years").size().rename("case_numbers").reset_index().to_csv(OUT / "05b_st_case_reuse.csv", index=False)
    freq = frequencies(data, ped_keys);    freq.to_csv(OUT / "06_category_frequencies.csv", index=False)
    cdrift = code_drift(data, ped_keys);   cdrift.to_csv(OUT / "07_code_drift.csv", index=False)
    geo = geo_profile(data, ped_keys);     geo.to_csv(OUT / "08_coordinates_geography.csv", index=False)
    struct = structure_checks(data, ped_keys); struct.to_csv(OUT / "08b_missingness_structure_consistency.csv", index=False)
    cen = census_profile(data);            cen.to_csv(OUT / "09_census_profile.csv", index=False)

    # summary markdown
    md = ["# Raw data profile (generated by pipeline/profile_raw.py)", "",
          f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Nothing in data/raw/ was modified.", "",
          "## Manifest", "", pd.DataFrame(manifest).to_markdown(index=False), "",
          "## Inventory (rows per file, national vs Florida)", "", pd.DataFrame(inventory).to_markdown(index=False), "",
          "## Unit of observation", "", unit.to_markdown(index=False), "",
          "## Columns present in some years only", "", (drift.to_markdown(index=False) if len(drift) else "none"), "",
          "## Keys, duplicates, cross-file consistency", "", keys.to_markdown(index=False), "",
          "## ST_CASE reuse across years", "",
          f"{(reuse['n_years'] > 1).sum():,} of {len(reuse):,} Florida case numbers appear in more than one year "
          f"(max {reuse['n_years'].max()} years).", "",
          "## Coordinates and geography", "", geo.to_markdown(index=False), "",
          "## Structure of the missingness and internal consistency", "", struct.to_markdown(index=False), "",
          "## Variable profile (unit of observation)", "", prof.to_markdown(index=False), "",
          "## Codes present in some years only", "", (cdrift.to_markdown(index=False) if len(cdrift) else "none"), "",
          "## Category frequencies, pooled 2020-2024", "",
          freq[freq["year"] == "2020-2024"].sort_values(["variable", "n"], ascending=[True, False]).to_markdown(index=False), "",
          "## Census county file", "", cen.to_markdown(index=False), ""]
    (OUT / "PROFILE.md").write_text("\n".join(md), encoding="utf-8")
    log(f"wrote {len(list(OUT.glob('*.csv')))} tables to {OUT.relative_to(ROOT)}/ and PROFILE.md")
    (EVID / "06_profile_run.log").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
