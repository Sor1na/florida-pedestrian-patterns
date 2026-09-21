#!/usr/bin/env python3
"""Do the CHECK constraints and the code labels agree?

The allowed codes live in two places: the CHECK constraints in sql/01_schema.sql
(what the database accepts) and the labels in sql/07_seed_codes.sql (what the
codes mean). This script reads both files and compares them, variable by variable.
A code that is accepted but has no label, or a label for a code that is never
accepted, is reported. Standard library only; needs no database.

    python tests/check_code_domains.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
schema = (ROOT / "sql" / "01_schema.sql").read_text(encoding="utf-8")
seeds = (ROOT / "sql" / "07_seed_codes.sql").read_text(encoding="utf-8")

# flat code lists that are fully enumerated in both places
ENUMERATED = ["rur_urb", "func_sys", "reljct2", "lgt_cond", "weather", "day_week",
              "hit_run", "per_typ", "inj_sev", "sex", "drinking", "pbcwalk", "pbswalk", "pedloc", "pedpos"]


def allowed_by_check(var: str) -> set[int]:
    m = re.search(rf"CONSTRAINT \w+_{var}_ck\s+CHECK \((.*?)\)\s*,?\s*(--.*)?$", schema, re.M)
    if not m:
        raise SystemExit(f"no CHECK found for {var}")
    expr = m.group(1)
    codes: set[int] = set()
    for lo, hi in re.findall(r"BETWEEN (\d+) AND (\d+)", expr):
        codes.update(range(int(lo), int(hi) + 1))
    for group in re.findall(r"IN \(([\d,\s]+)\)", expr):
        codes.update(int(x) for x in group.split(","))
    for single in re.findall(rf"{var} = (\d+)", expr):
        codes.add(int(single))
    return codes


def labelled(var: str) -> set[int]:
    return {int(c) for c in re.findall(rf"\('{var}',\s*(\d+),", seeds)}


failures = 0
for var in ENUMERATED:
    a, b = allowed_by_check(var), labelled(var)
    ok = a == b
    failures += not ok
    note = "" if ok else f"   accepted but unlabelled: {sorted(a - b)}   labelled but never accepted: {sorted(b - a)}"
    print(f"  {'PASS' if ok else 'FAIL'}  {var:<9} {len(a):>2} codes accepted, {len(b):>2} labelled{note}")

# PBCAT: every type names a group that exists; every group has at least one type
groups = {int(g) for g in re.findall(r"^\s*\((\d+), '[^']*(?:''[^']*)*'\)[,;]", seeds, re.M)}
types = [(int(t), int(g)) for t, g in re.findall(r"^\s*\((\d+), '.*', (\d+)\)[,;]", seeds, re.M)]
orphans = sorted(t for t, g in types if g not in groups)
empty = sorted(groups - {g for _, g in types})
ok = not orphans and not empty
failures += not ok
print(f"  {'PASS' if ok else 'FAIL'}  pbcat     {len(types)} crash types in {len(groups)} crash groups"
      + ("" if ok else f"   types without a group: {orphans}   groups without a type: {empty}"))

print()
print("CHECK constraints and code labels agree." if not failures else f"{failures} mismatch(es).")
sys.exit(1 if failures else 0)
