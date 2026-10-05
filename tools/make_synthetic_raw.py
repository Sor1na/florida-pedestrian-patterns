#!/usr/bin/env python3
"""
make_synthetic_raw.py - deterministic SYNTHETIC stand-ins for the raw input files.

Writes five FARS{year}NationalCSV.zip files (2020-2024) and a co-est2025-alldata.csv
with the layout of the real NHTSA FARS National CSV zips and the Census Vintage 2025
county file, so that pipeline/etl.py can be demonstrated end to end without real data:

    python tools/make_synthetic_raw.py                     # writes data/synthetic/clean/
    python tools/make_synthetic_raw.py --out DIR [--seed 7]

EVERY ROW IS MADE UP. Real FARS rows describe real deaths, and the project keeps them
out of the repository (they stay in data/raw/ and the local database). This generator
lets anyone run the pipeline without them. The files copy the structure that the
Week 6 profile measured on the real files (docs/Week6_Data_Cleaning_Plan_Shkirpan.md,
sections 1-2): member names whose case and folder change from year to year, three 2020
members in cp1252, a stray space in one header, a column present in 2020 only, case
numbers that restart every year, multi-victim crashes, coded unknowns, coordinate
fillers, non-Florida rows for the state filter to remove, and a latin-1 Census file.
The distributions only roughly follow the real ones. No count here is a real count.

Outputs (in the output directory, which is git-ignored):
    FARS{year}NationalCSV.zip   accident, vehicle, person, pbtype, parkwork + 2 unused members
    co-est2025-alldata.csv      Florida state row, 67 counties, 11 rows of other states (latin-1)
    sources.csv                 the pinned input set: file, url, bytes, sha256, release
    expected_counts.csv         the reconciliation totals (stand-in for NHTSA's published counts)
    README.txt                  says that the files are synthetic

The same seed gives byte-identical files: fixed member order, timestamps and attributes,
so the SHA-256 values in sources.csv can be reproduced. (Deflate output depends on the
zlib build. CPython with the standard zlib gives identical bytes.)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import random
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YEARS = [2020, 2021, 2022, 2023, 2024]
FL = 12
ZIP_TIME = (2026, 9, 27, 0, 0, 0)
RETRIEVED = "2026-09-27"
BASE_URL = "https://synthetic.invalid"

# Florida counties exactly as in sql/06_seed_county.sql, with a rough 2020 population (thousands)
COUNTIES = {
    1: ("Alachua", 279), 3: ("Baker", 28), 5: ("Bay", 175), 7: ("Bradford", 28), 9: ("Brevard", 607),
    11: ("Broward", 1944), 13: ("Calhoun", 13.6), 15: ("Charlotte", 187), 17: ("Citrus", 154), 19: ("Clay", 219),
    21: ("Collier", 376), 23: ("Columbia", 69), 27: ("DeSoto", 34), 29: ("Dixie", 16.8), 31: ("Duval", 996),
    33: ("Escambia", 321), 35: ("Flagler", 116), 37: ("Franklin", 12.4), 39: ("Gadsden", 43.8), 41: ("Gilchrist", 17.9),
    43: ("Glades", 12.1), 45: ("Gulf", 14.2), 47: ("Hamilton", 14), 49: ("Hardee", 25.3), 51: ("Hendry", 39.6),
    53: ("Hernando", 194), 55: ("Highlands", 101), 57: ("Hillsborough", 1460), 59: ("Holmes", 19.7),
    61: ("Indian River", 160), 63: ("Jackson", 48), 65: ("Jefferson", 14.5), 67: ("Lafayette", 8.2), 69: ("Lake", 384),
    71: ("Lee", 760), 73: ("Leon", 292), 75: ("Levy", 42.9), 77: ("Liberty", 8.1), 79: ("Madison", 17.9),
    81: ("Manatee", 400), 83: ("Marion", 375), 85: ("Martin", 158), 86: ("Miami-Dade", 2700), 87: ("Monroe", 82.9),
    89: ("Nassau", 90.4), 91: ("Okaloosa", 211), 93: ("Okeechobee", 39.6), 95: ("Orange", 1430), 97: ("Osceola", 388),
    99: ("Palm Beach", 1490), 101: ("Pasco", 561), 103: ("Pinellas", 959), 105: ("Polk", 725), 107: ("Putnam", 73.3),
    109: ("St. Johns", 273), 111: ("St. Lucie", 329), 113: ("Santa Rosa", 188), 115: ("Sarasota", 434),
    117: ("Seminole", 470), 119: ("Sumter", 129), 121: ("Suwannee", 43.5), 123: ("Taylor", 21.8), 125: ("Union", 16.1),
    127: ("Volusia", 553), 129: ("Wakulla", 34), 131: ("Walton", 75), 133: ("Washington", 25.3),
}
COUNTY_W = {c: 0.55 for c in COUNTIES} | {86: 12, 11: 9.7, 57: 7.6, 99: 7.1, 95: 7.1, 31: 5.7, 103: 5.0,
                                          105: 3.3, 101: 3.3, 71: 3.3, 9: 2.5, 127: 2.5}
STATENAME = {1: "Alabama", 12: "Florida", 13: "Georgia", 48: "Texas"}
# other states: (about how many crashes per year, counties, lat/lon box)
OTHER_STATES = {
    1: (50, {73: "JEFFERSON", 97: "MOBILE", 89: "MADISON", 101: "MONTGOMERY"}, (30.2, 35.0, -88.4, -84.9)),
    13: (70, {121: "FULTON", 89: "DEKALB", 135: "GWINNETT", 67: "COBB", 51: "CHATHAM"}, (30.4, 35.0, -85.6, -80.8)),
    48: (80, {201: "HARRIS", 113: "DALLAS", 29: "BEXAR", 453: "TRAVIS", 439: "TARRANT"}, (25.8, 36.5, -106.6, -93.5)),
}
FL_ROADS = ["US-192", "SR-60", "NW 27TH AVE", "US-1", "US-441", "SR-50", "US-19", "SR-436", "BISCAYNE BLVD",
            "W FLAGLER ST", "N DALE MABRY HWY", "SR-7", "US-27", "COLONIAL DR", "SEMORAN BLVD", "BEACH BLVD",
            "CR-579", "MONCRIEF RD", "OKEECHOBEE BLVD", "SW 8TH ST", "E OAKLAND PARK BLVD", "US-92", "SR-580",
            "NEBRASKA AVE", "US-301", "SR-A1A", "MLK JR BLVD", "N MAIN ST", "PALM AVE", "SR-84"]
FL_FREEWAYS = {1: ["I-95", "I-4", "I-75", "I-10", "I-275"], 2: ["SR-408", "SR-836", "SR-826", "TURNPIKE", "SR-417"]}
OTHER_ROADS = ["I-20", "I-65", "US-280", "SR-6", "IH-35", "US-59", "I-285", "PEACHTREE RD", "FM-1960", "WESTHEIMER RD"]

# PBCAT crash types emitted: pedctype -> (pedcgp, weight, label); all of them are in sql/07_seed_codes.sql
PBCAT = {
    760: (750, 18, "Pedestrian Failed to Yield"), 770: (750, 7, "Motorist Failed to Yield"),
    610: (600, 6, "Standing in Roadway"), 620: (600, 6, "Walking in Roadway"), 313: (600, 3, "Lying in Roadway"),
    680: (990, 7, "Not At Intersection - Other/Unknown"), 690: (990, 3, "At Intersection - Other/Unknown"),
    900: (990, 3, "Other - Unknown Location"), 910: (910, 6, "Crossing an Expressway"),
    410: (400, 3, "Walking/Running Along Roadway With Traffic - From Behind"),
    420: (400, 1.5, "Walking/Running Along Roadway With Traffic - From Front"),
    430: (400, 1, "Walking/Running Along Roadway Against Traffic - From Behind"),
    440: (400, 1.5, "Walking/Running Along Roadway Against Traffic - From Front"),
    459: (400, 1.5, "Walking/Running Along Roadway - Direction/Position Unknown"),
    741: (740, 3, "Dash - Run, No Visual Obstruction Noted"), 742: (740, 2, "Dart-Out - Visual Obstruction Noted"),
    781: (790, 1, "Motorist Left Turn - Parallel Paths"), 782: (790, 1, "Motorist Left Turn - Perpendicular Paths"),
    791: (790, 0.7, "Motorist Right Turn - Parallel Paths"), 799: (790, 0.8, "Motorist Turn/Merge - Other/Unknown"),
    150: (100, 1.2, "Motor Vehicle Loss of Control"), 160: (100, 1, "Pedestrian Loss of Control"),
    130: (100, 0.6, "Pedestrian on Vehicle"), 190: (100, 0.8, "Other Unusual Circumstances"),
    230: (100, 0.6, "Disabled Vehicle-Related"), 213: (200, 0.8, "Backing Vehicle - Trafficway"),
    214: (200, 0.6, "Backing Vehicle - Non-Trafficway - Parking Lot"), 311: (310, 0.6, "Working in Roadway"),
    341: (340, 0.8, "Transit Bus Stop-Related"), 320: (350, 0.6, "Entering/Exiting Parked or Stopped Vehicle"),
    461: (460, 0.4, "Motorist Entering Driveway"), 465: (460, 0.4, "Motorist Exiting Driveway"),
    510: (500, 0.3, "Waiting to Cross - Vehicle Turning"), 520: (500, 0.4, "Waiting to Cross - Vehicle Not Turning"),
    710: (720, 0.5, "Multiple Threat"), 830: (800, 0.8, "Non-Trafficway - Parking Lot"),
    890: (800, 0.5, "Non-Trafficway - Other/Unknown"),
}
PBCAT_COLS = ["PBCWALK", "PBSWALK", "PEDCTYPE", "PEDCTYPENAME", "PEDCGP", "PEDLOC", "PEDPOS", "PEDDIR", "MOTDIR"]
AT_INTERSECTION = {690, 781, 782, 791, 799, 510, 520, 710}
NON_TRAFFICWAY = {830, 890, 214}
PEDPOS_BY_LOC = {1: {2: 60, 1: 30, 3: 10}, 2: {3: 60, 2: 25, 1: 15}, 3: {3: 88, 4: 6, 5: 3, 6: 3}, 4: {7: 40, 8: 60}}
DIRECTION = {1: 24, 2: 24, 3: 24, 4: 24, 9: 4}

HOUR_PED = {h: 4.0 for h in range(0, 6)} | {h: 2.2 for h in range(6, 12)} | {h: 1.7 for h in range(12, 18)} \
    | {h: 9.0 for h in range(18, 21)} | {h: 8.7 for h in range(21, 24)}
HOUR_ANY = {h: 2.0 if 15 <= h <= 22 else 1.0 for h in range(24)}
FUNC_URBAN = {3: 46, 4: 23, 5: 11, 7: 10, 1: 6.6, 6: 2, 2: 1.8}
FUNC_RURAL = {3: 35, 4: 15, 5: 25, 6: 8, 7: 10, 1: 7}
SPEED = {1: {55: 1, 60: 2, 65: 3, 70: 4}, 2: {45: 1, 50: 1, 55: 3, 60: 2, 65: 2},
         3: {35: 1, 40: 2, 45: 4, 50: 2, 55: 2}, 4: {30: 1, 35: 3, 40: 3, 45: 3, 50: 1},
         5: {25: 1, 30: 2, 35: 3, 40: 2, 45: 2}, 6: {25: 1, 30: 2, 35: 2, 45: 1, 55: 1},
         7: {15: 0.3, 20: 0.5, 25: 3, 30: 3, 35: 1.5}, 96: {15: 1, 25: 2, 30: 1}, 98: {35: 1, 45: 1}}
RELJCT2 = {1: 71, 3: 20, 2: 5, 8: 2, 5: 0.6, 18: 0.4, 98: 0.3}
BODY = {4: 31, 34: 15, 14: 15, 15: 6, 2: 3, 3: 3, 20: 4, 31: 3, 16: 2, 21: 1, 66: 2, 64: 1, 50: 0.3, 80: 1, 99: 0.2}
PARKED_BODY = {4: "Automobile - 4-door Sedan", 14: "Utility - Compact", 34: "Pickup - Light",
               20: "Van - Minivan", 64: "Truck - Single-Unit Straight"}
MAKES = {12: 20, 20: 15, 49: 18, 37: 12, 35: 10, 7: 8, 52: 5, 63: 4}
NVEH = {"ped": {1: 86, 2: 11, 3: 3}, "occ": {1: 45, 2: 45, 3: 10}, "pedinj": {1: 50, 2: 50}, "cyc": {1: 95, 2: 5}}
HIT_P = {"ped": 0.19, "cyc": 0.15, "pedinj": 0.0, "occ": 0.0}
OTHER_FL_KINDS = {"occ": 65, "pedinj": 20, "cyc": 15}
NONFL_KINDS = {"ped": 35, "occ": 55, "pedinj": 5, "cyc": 5}

HEADERS = {
    "accident": ["STATE", "STATENAME", "ST_CASE", "PEDS", "PERNOTMVIT", "VE_TOTAL", "VE_FORMS", "PVH_INVL", "PERSONS",
                 "PERMVIT", "COUNTY", "COUNTYNAME", "MONTH", "DAY", "DAY_WEEK", "YEAR", "HOUR", "MINUTE", "RUR_URB",
                 "FUNC_SYS", "TWAY_ID", "RELJCT2", "LGT_COND", "WEATHER", "LATITUDE", "LONGITUD", "FATALS"],
    "factor": ["STATE", "ST_CASE", "VEH_NO", "VEHICLECC", "VEHICLECCNAME"],
    "parkwork": ["STATE", "STATENAME", "ST_CASE", "VEH_NO", "PBODYTYP", "PBODYTYPNAME", "PMAKE", "PMOD_YEAR"],
    "pbtype": ["STATE", "STATENAME", "ST_CASE", "VEH_NO", "PER_NO", "PBPTYPE", "PBAGE", "PBSEX", "PBCWALK", "PBSWALK",
               "PEDCTYPE", "PEDCTYPENAME", "PEDCGP", "PEDLOC", "PEDPOS", "PEDDIR", "MOTDIR"],
    "person": ["STATE", "STATENAME", "ST_CASE", "VEH_NO", "PER_NO", "STR_VEH", "AGE", "SEX", "PER_TYP", "INJ_SEV",
               "SEAT_POS", "AIR_BAG", "DRINKING"],
    "vehicle": ["STATE", "STATENAME", "ST_CASE", "VEH_NO", "NUMOCCS", "HIT_RUN", "MAKE", "MOD_YEAR", "BODY_TYP",
                "VSPD_LIM"],
    "weather": ["STATE", "ST_CASE", "WEATHER", "WEATHERNAME"],
}
MEMBERS = list(HEADERS)                       # alphabetical, as in the real zips
CP1252_2020 = {"accident", "pbtype", "parkwork"}
WEATHER_NAME = {1: "Clear", 2: "Rain", 5: "Fog, Smog, Smoke", 10: "Cloudy", 99: "Reported as Unknown"}


def pick(rng: random.Random, table: dict):
    keys = list(table)
    return rng.choices(keys, weights=[table[k] for k in keys])[0]


def dash(label: str, year: int) -> str:
    """The 2020 export writes en dashes in label text (cp1252 byte 0x96, which is not valid UTF-8)."""
    return label.replace(" - ", " \u2013 ") if year == 2020 else label


# ---------------------------------------------------------------------------
# One crash: accident row, vehicles, persons, pbtype rows, parked vehicles
# ---------------------------------------------------------------------------
def light(rng: random.Random, hour: int, year: int) -> int:
    if 8 <= hour <= 16:
        table = {1: 99.5, 9: 0.5}
    elif hour in (7, 17):
        table = {1: 75, 4 if hour == 7 else 5: 25}
    elif hour in (6, 18, 19):
        table = {4 if hour == 6 else 5: 30, 3: 40, 2: 25, 1: 5 if hour == 18 else 0}
    else:                                      # 20:00-05:59, never daylight
        table = {3: 52, 2: 44, 6: 3, 9: 0.5} | ({8: 0.4} if year in (2020, 2024) else {})
    return pick(rng, table)


def scene(rng: random.Random, year: int, state: int, kind: str) -> tuple[dict, int]:
    ped = kind != "occ"
    hour = pick(rng, HOUR_PED if ped else HOUR_ANY)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31)
    rur = pick(rng, {2: 89, 1: 10} if ped else {2: 55, 1: 45})
    func = pick(rng, FUNC_RURAL if rur == 1 else FUNC_URBAN)
    if rng.random() < 0.004:
        rur, func = 6, 96                      # not in the state inventory: both codes together
    elif year in (2022, 2024) and rng.random() < 0.003:
        func = 98
    speed = pick(rng, SPEED[func])
    if func != 1 and rng.random() < 0.005:
        speed = 0
    if state == FL:
        county = pick(rng, COUNTY_W)
        cname = COUNTIES[county][0]
        lat, lon = rng.uniform(24.56, 31.0), rng.uniform(-87.4, -80.04)
        tway = rng.choice(FL_FREEWAYS[func]) if func in (1, 2) else rng.choice(FL_ROADS)
    else:
        _, counties, (la0, la1, lo0, lo1) = OTHER_STATES[state]
        county = rng.choice(list(counties))
        cname, lat, lon = counties[county], rng.uniform(la0, la1), rng.uniform(lo0, lo1)
        tway = rng.choice(OTHER_ROADS)
    acc = dict(COUNTY=county, COUNTYNAME=f"{cname.upper()} ({county})", MONTH=month, DAY=day,
               DAY_WEEK=dt.date(year, month, day).isoweekday() % 7 + 1, YEAR=year, HOUR=hour,
               MINUTE=rng.randint(0, 59), RUR_URB=rur, FUNC_SYS=func, TWAY_ID=tway, RELJCT2=pick(rng, RELJCT2),
               LGT_COND=light(rng, hour, year),
               WEATHER=pick(rng, {1: 75, 10: 13, 2: 10, 5: 1.5} | ({99: 0.6} if year >= 2022 else {})),
               LATITUDE=f"{lat:.8f}", LONGITUD=f"{lon:.8f}")
    return acc, speed


def ped_codes(rng: random.Random, year: int) -> dict:
    t = pick(rng, {k: v[1] for k, v in PBCAT.items()})
    if t in NON_TRAFFICWAY:
        loc = 4
    elif t in AT_INTERSECTION:
        loc = pick(rng, {1: 70, 2: 30})
    elif t == 900 and rng.random() < 0.05:
        loc = 9
    else:
        loc = pick(rng, {3: 88, 2: 10, 1: 2})
    pos = 9 if loc == 9 else pick(rng, PEDPOS_BY_LOC[loc])
    if loc in (1, 2, 3) and rng.random() < 0.02:
        pos = 9
    cwalk = 1 if pos == 2 or (loc in (1, 2) and rng.random() < 0.05) else 0
    if rng.random() < 0.001:
        cwalk = 9
    return dict(PBCWALK=cwalk, PBSWALK=pick(rng, {0: 70.9, 1: 28.8, 9: 0.3}), PEDCTYPE=t,
                PEDCTYPENAME=dash(PBCAT[t][2], year), PEDCGP=PBCAT[t][0], PEDLOC=loc, PEDPOS=pos,
                PEDDIR=pick(rng, DIRECTION), MOTDIR=pick(rng, DIRECTION))


def ped_person(rng: random.Random, year: int) -> tuple[int, int, int]:
    band = pick(rng, {(0, 14): 2.2, (15, 24): 6.9, (25, 44): 29.5, (45, 64): 33.2, (65, 98): 22.5, 998: 2.0, 999: 3.7})
    age = band if isinstance(band, int) else rng.randint(*band)
    unk = 0.33 + 0.01 * (year - 2020)          # DRINKING unknown share rises by year
    drink = pick(rng, {0: (1 - unk) * 0.72, 1: (1 - unk) * 0.28, 8: unk * 0.3, 9: unk * 0.7})
    return age, pick(rng, {1: 67.7, 2: 28, 8: 1, 9: 3.3}), drink


def make_crash(rng: random.Random, year: int, state: int, k: int, kind: str, ped_deaths: int,
               force_parked: bool = False) -> dict:
    st_case = state * 10_000 + k
    acc, speed = scene(rng, year, state, kind)
    n_veh = pick(rng, NVEH[kind])
    sv = 2 if n_veh > 1 and rng.random() < 0.2 else 1
    hit = rng.random() < HIT_P[kind]
    veh, per, pb = [], [], []
    for v in range(1, n_veh + 1):
        hr = int(hit and v == sv)
        body = 99 if hr and rng.random() < 0.55 else pick(rng, BODY)
        if acc["FUNC_SYS"] != 1 and rng.random() < (0.185 if hr else 0.026):
            vspd = pick(rng, {99: 7, 98: 3})
        elif v > 1 and speed and rng.random() < 0.05:
            vspd = min(70, max(15, speed + rng.choice([-10, -5, 5])))
        else:
            vspd = speed
        n_occ = 1 + pick(rng, {0: 70, 1: 20, 2: 10})
        for p_no in range(1, n_occ + 1):
            gone = hr and p_no == 1                # the driver who left the scene: unknowns
            per.append(dict(VEH_NO=v, PER_NO=p_no, STR_VEH=0, PER_TYP=1 if p_no == 1 else 2,
                            INJ_SEV=9 if gone else pick(rng, {0: 85, 1: 7, 2: 5, 3: 3}),
                            AGE=999 if gone else rng.randint(16, 90) if p_no == 1 else rng.randint(0, 85),
                            SEX=9 if gone else pick(rng, {1: 60, 2: 40}),
                            DRINKING=9 if gone else pick(rng, {0: 80, 1: 6, 8: 4, 9: 10}),
                            SEAT_POS=11 if p_no == 1 else rng.choice([13, 21, 23]),
                            AIR_BAG=pick(rng, {20: 70, 1: 20, 98: 10})))
        veh.append(dict(VEH_NO=v, NUMOCCS=n_occ, HIT_RUN=hr, MAKE=99 if body == 99 else pick(rng, MAKES),
                        MOD_YEAR=9999 if body == 99 else rng.randint(1998, year), BODY_TYP=body, VSPD_LIM=vspd))
    occupants = [p for p in per if p["INJ_SEV"] != 9]
    if kind in ("occ", "pedinj"):              # FARS crashes are fatal: someone in a vehicle died
        for p in rng.sample(occupants, min(len(occupants), 2 if rng.random() < 0.15 else 1)):
            p["INJ_SEV"] = 4
    elif kind == "ped" and n_veh > 1 and rng.random() < 0.1:
        others = [p for p in occupants if p["VEH_NO"] != sv]
        rng.choice(others)["INJ_SEV"] = 4
    nonmot = {"ped": [(5, 4)] * ped_deaths + ([(5, pick(rng, {3: 2, 2: 1}))] if rng.random() < 0.03 else []),
              "pedinj": [(5, pick(rng, {3: 2, 2: 1, 1: 1}))], "cyc": [(6, 4)], "occ": []}[kind]
    for n, (pt, inj) in enumerate(nonmot, 1):
        age, sex, drink = ped_person(rng, year)
        per.append(dict(VEH_NO=0, PER_NO=n, STR_VEH=sv, PER_TYP=pt, INJ_SEV=inj, AGE=age, SEX=sex,
                        DRINKING=drink, SEAT_POS=0, AIR_BAG=0))
        if pt == 6:                            # cyclist: the pedestrian fields say "not a pedestrian"
            codes = dict(PBCWALK=pick(rng, {0: 80, 1: 20}), PBSWALK=pick(rng, {0: 70, 1: 30}), PEDCTYPE=0,
                         PEDCTYPENAME="Not a Pedestrian", PEDCGP=0, PEDLOC=7, PEDPOS=77, PEDDIR=0, MOTDIR=0)
        elif n > 1 and rng.random() < 0.7:     # people walking together share the crash type
            codes = {c: pb[0][c] for c in PBCAT_COLS}
        else:
            codes = ped_codes(rng, year)
        pb.append(dict(VEH_NO=0, PER_NO=n, PBPTYPE=pt, PBAGE=age, PBSEX=sex, **codes))
    per.sort(key=lambda p: (p["VEH_NO"], p["PER_NO"]))
    pw = []
    if force_parked or rng.random() < 0.03:    # parked vehicles are numbered after the in-transport ones
        b = rng.choice(list(PARKED_BODY))
        pw.append(dict(VEH_NO=n_veh + 1, PBODYTYP=b, PBODYTYPNAME=dash(PARKED_BODY[b], year),
                       PMAKE=pick(rng, MAKES), PMOD_YEAR=rng.randint(1998, year)))
    acc.update(PEDS=len(nonmot), PERNOTMVIT=len(nonmot), VE_TOTAL=n_veh + len(pw), VE_FORMS=n_veh,
               PVH_INVL=len(pw), PERSONS=len(per) - len(nonmot), PERMVIT=len(per) - len(nonmot),
               FATALS=sum(p["INJ_SEV"] == 4 for p in per),
               DRUNK_DR=sum(p["PER_TYP"] == 1 and p["DRINKING"] == 1 for p in per))
    head = dict(STATE=state, STATENAME=STATENAME[state], ST_CASE=st_case)
    return dict(state=state, st_case=st_case, accident=[head | acc],
                vehicle=[head | r for r in veh], person=[head | r for r in per], pbtype=[head | r for r in pb],
                parkwork=[head | r for r in pw],
                factor=[dict(STATE=state, ST_CASE=st_case, VEH_NO=r["VEH_NO"], VEHICLECC=0, VEHICLECCNAME="None")
                        for r in veh],
                weather=[dict(STATE=state, ST_CASE=st_case, WEATHER=acc["WEATHER"],
                              WEATHERNAME=WEATHER_NAME[acc["WEATHER"]])])


def build_year(year: int, seed: int) -> list[dict]:
    rng = random.Random(seed * 10_000 + year)
    n_ped, n_other = rng.randint(90, 130), rng.randint(140, 160)
    kinds = ["ped"] * n_ped + [pick(rng, OTHER_FL_KINDS) for _ in range(n_other)]
    rng.shuffle(kinds)                         # case numbers 1..n restart every year
    ped_idx = [i for i, k in enumerate(kinds) if k == "ped"]
    deaths = dict.fromkeys(ped_idx, 1)
    multi = rng.sample(ped_idx, rng.randint(6, 10) + 1)
    deaths.update(dict.fromkeys(multi[:-1], 2) | {multi[-1]: 3})
    crashes = [make_crash(rng, year, FL, i + 1, kind, deaths.get(i, 0), force_parked=(i == ped_idx[2]))
               for i, kind in enumerate(kinds)]
    fillers = rng.sample(ped_idx, 2 if year == 2022 else 1)
    for j, i in enumerate(fillers):
        crashes[i]["accident"][0].update(LATITUDE="99.99990000" if j else "77.77770000",
                                         LONGITUD="999.99990000" if j else "777.77770000")
    # RUR_URB 8 "not reported" / 9 "unknown": a few in 2023, about 4% in the provisional 2024 file
    known = [i for i in ped_idx if crashes[i]["accident"][0]["RUR_URB"] in (1, 2)]
    for j, i in enumerate(rng.sample(known, {2023: 2, 2024: round(0.04 * n_ped)}.get(year, 0))):
        crashes[i]["accident"][0]["RUR_URB"] = 9 if year == 2024 and j % 2 else 8
    plain = [i for i in ped_idx if i not in fillers]
    if year == 2020:                          # two crashes share one point; one road name is not ASCII
        a, b = crashes[plain[5]]["accident"][0], crashes[plain[6]]["accident"][0]
        b.update(LATITUDE=a["LATITUDE"], LONGITUD=a["LONGITUD"])
        crashes[plain[8]]["accident"][0]["TWAY_ID"] = "AVENIDA PE\u00d1A"
    if year == 2022:                           # non-ASCII in a UTF-8 file too
        crashes[plain[8]]["accident"][0]["TWAY_ID"] = "CALLE PE\u00d1A"
    for state, (n, _, _) in OTHER_STATES.items():
        for k in range(1, n + rng.randint(-8, 8) + 1):
            crashes.append(make_crash(rng, year, state, k, pick(rng, NONFL_KINDS), 1))
    return sorted(crashes, key=lambda c: c["st_case"])


# ---------------------------------------------------------------------------
# Writing: CSV members, deterministic zips, Census file, manifest files
# ---------------------------------------------------------------------------
def member_path(year: int, name: str) -> str:
    if year <= 2021:
        return f"{name}.csv"                                  # zip root, lower case
    folder = f"FARS{year}NationalCSV/"
    return folder + {2022: f"{name}.csv", 2023: f"{name.upper()}.CSV", 2024: f"{name.capitalize()}.csv"}[year]


def csv_text(header: list[str], rows: list[dict], header_out: list[str] | None = None, eol: str = "\r\n") -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=eol)
    w.writerow(header_out or header)
    w.writerows([r[h] for h in header] for r in rows)
    return buf.getvalue()


def write_zip(path: Path, year: int, crashes: list[dict]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        if year >= 2022:
            d = zipfile.ZipInfo(f"FARS{year}NationalCSV/", date_time=ZIP_TIME)
            d.create_system, d.external_attr = 3, (0o40755 << 16) | 0x10
            d.CRC = d.compress_size = d.file_size = 0   # set here: Python 3.11's mkdir(ZipInfo) does not
            zf.mkdir(d)
        for name in MEMBERS:
            header = HEADERS[name] + (["DRUNK_DR"] if name == "accident" and year == 2020 else [])
            header_out = [" STATE"] + header[1:] if name == "accident" and year == 2021 else None
            rows = [r for c in crashes for r in c[name]]
            enc = "cp1252" if year == 2020 and name in CP1252_2020 else "utf-8"
            info = zipfile.ZipInfo(member_path(year, name), date_time=ZIP_TIME)
            info.compress_type, info.create_system, info.external_attr = zipfile.ZIP_DEFLATED, 3, 0o644 << 16
            zf.writestr(info, csv_text(header, rows, header_out).encode(enc), compresslevel=6)


def write_census(path: Path, seed: int) -> None:
    rng = random.Random(seed * 10_000 + 1)
    years = range(2020, 2026)

    def series(base: float) -> list[int]:
        rate, p, out = rng.uniform(0.003, 0.025), base * (1 + rng.uniform(0.0005, 0.003)), []
        for y in years:
            p *= 1 if y == 2020 else 1 + rate + rng.uniform(-0.002, 0.002)
            out.append(round(p))
        return [round(base)] + out

    region = {"01": (3, 6), "12": (3, 5), "13": (3, 5), "35": (4, 8), "48": (3, 7)}
    rows = [("050", "12", f"{fips:03d}", "Florida", f"{name} County", series(k * 1000 * rng.uniform(0.98, 1.02)))
            for fips, (name, k) in COUNTIES.items()]
    state = [sum(r[5][i] for r in rows) for i in range(7)]
    others = [("01", "000", "Alabama", "Alabama", 5_031_000), ("01", "073", "Alabama", "Jefferson County", 674_000),
              ("01", "097", "Alabama", "Mobile County", 414_000), ("13", "000", "Georgia", "Georgia", 10_730_000),
              ("13", "121", "Georgia", "Fulton County", 1_067_000),
              ("13", "135", "Georgia", "Gwinnett County", 958_000),
              ("35", "000", "New Mexico", "New Mexico", 2_118_000),
              ("35", "001", "New Mexico", "Bernalillo County", 676_000),
              ("35", "013", "New Mexico", "Do\u00f1a Ana County", 219_000), ("48", "000", "Texas", "Texas", 29_230_000),
              ("48", "201", "Texas", "Harris County", 4_735_000)]
    rows = ([("040", "12", "000", "Florida", "Florida", state)] + rows
            + [("040" if c == "000" else "050", s, c, sn, cn, series(p)) for s, c, sn, cn, p in others])
    rows.sort(key=lambda r: (r[1], r[2]))
    header = ["SUMLEV", "REGION", "DIVISION", "STATE", "COUNTY", "STNAME", "CTYNAME", "ESTIMATESBASE2020",
              *[f"POPESTIMATE{y}" for y in years], "NPOPCHG2021", "NPOPCHG2022", "NPOPCHG2023"]
    recs = [dict(zip(header, [sl, *region[st], st, co, sn, cn, *v, v[2] - v[1], v[3] - v[2], v[4] - v[3]]))
            for sl, st, co, sn, cn, v in rows]
    path.write_bytes(csv_text(header, recs).encode("latin-1"))   # latin-1 (n-tilde in Dona Ana)


def counts(crashes: list[dict]) -> dict:
    """The reconciliation totals of one year, counted on the rows as written (Florida = STATE 12)."""
    fl = [c for c in crashes if c["state"] == FL]
    out = {f"{m}_fl_rows": sum(len(c[m]) for c in fl) for m in ["accident", "vehicle", "person", "pbtype"]}
    peds = [c["st_case"] for c in fl for p in c["person"] if p["PER_TYP"] == 5 and p["INJ_SEV"] == 4]
    return out | {"ped_fatalities": len(peds), "crashes_with_ped_fatality": len(set(peds))}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write synthetic FARS/Census raw files (every row is made up).")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synthetic" / "clean", help="output directory")
    ap.add_argument("--seed", type=int, default=7, help="random seed (same seed = same bytes)")
    args = ap.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    sources, expected, per_year = [], [], {}
    for y in YEARS:
        crashes = build_year(y, args.seed)
        path = out / f"FARS{y}NationalCSV.zip"
        write_zip(path, y, crashes)
        per_year[y] = counts(crashes)
        sources.append(dict(source="FARS", data_year=y, file_name=path.name,
                            url=f"{BASE_URL}/FARS/{y}/{path.name}", bytes=path.stat().st_size, sha256=sha256(path),
                            release="Annual Report File" if y == 2024 else "Final", retrieved_on=RETRIEVED))
        expected += [dict(source="FARS", data_year=y, measure=m, expected=n) for m, n in per_year[y].items()]
    census = out / "co-est2025-alldata.csv"
    write_census(census, args.seed)
    sources.append(dict(source="CENSUS_POPEST", data_year="", file_name=census.name,
                        url=f"{BASE_URL}/census/{census.name}", bytes=census.stat().st_size, sha256=sha256(census),
                        release="Vintage 2025", retrieved_on=RETRIEVED))
    expected.append(dict(source="CENSUS_POPEST", data_year="", measure="fl_county_rows", expected=len(COUNTIES)))
    for name, rows in [("sources.csv", sources), ("expected_counts.csv", expected)]:
        (out / name).write_text(csv_text(list(rows[0]), rows, eol="\n"), encoding="utf-8")
    (out / "README.txt").write_text(
        "SYNTHETIC DATA: every row in these files is made up.\n"
        f"Generated by tools/make_synthetic_raw.py (seed {args.seed}). These are NOT real NHTSA FARS or Census data;\n"
        "they copy only the file layout, so pipeline/etl.py can be demonstrated without the real downloads.\n",
        encoding="utf-8")

    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"wrote {shown}/  (synthetic, seed {args.seed})")
    for s in sources:
        print(f"  {s['file_name']:<28} {s['bytes']:>9,} bytes  sha256 {s['sha256'][:12]}")
    print("  year  ped_fatalities  crashes  | Florida rows: accident vehicle person pbtype")
    for y, c in per_year.items():
        print(f"  {y}  {c['ped_fatalities']:>14}  {c['crashes_with_ped_fatality']:>7}  |"
              f"{c['accident_fl_rows']:>23} {c['vehicle_fl_rows']:>7} {c['person_fl_rows']:>6}"
              f" {c['pbtype_fl_rows']:>6}")
    print("  also: sources.csv, expected_counts.csv, README.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
