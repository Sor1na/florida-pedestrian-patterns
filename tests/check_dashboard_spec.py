#!/usr/bin/env python3
"""Check the Week 12 dashboard specification against the repository.

The design document (docs/Week12_Dashboard_Design_Shkirpan.md) has a machine-
readable counterpart in dashboard/: views.csv (one row per view), limitations.csv
(the limitation blocks), palette.csv (every color pair with its contrast
requirement) and countermeasures.csv (the condition -> countermeasure matrix).
This script reads them and verifies the completion criteria of the design:

  1. every view names at least one audience task (T1-T4), and every task has a view;
  2. every chart form is one of the forms the design allows for its comparison;
  3. the views run context -> finding -> action, with context first and at least
     one view in every stage;
  4. every finding and action view names the uncertainty element drawn beside it
     and at least one limitation block; every limitation block is placed beside a
     view and is at most 40 words;
  5. every view has alternative text, and no title or alt text uses the words the
     design forbids ("most dangerous", "risk", "prevent", "cause");
  6. every source field exists: a column of a view in sql/04_views.sql, a column of
     a table in sql/01_schema.sql, a header of a CSV under docs/evidence/week11/,
     docs/profile/ or dashboard/, or a key path in results_summary.json;
  7. every palette pair clears its WCAG 2 contrast requirement, or names the
     mitigation the design gives it; the two series colors stay apart under
     simulated protanopia and deuteranopia (Machado, Oliveira & Fernandes 2009,
     severity 1.0; Euclidean distance in OKLab x100 >= 8) and under normal vision
     (>= 15), keep OKLCH chroma >= 0.10 and lightness within 0.43-0.77; the map and
     heat-table ramps are one hue, monotone in lightness, with adjacent steps at
     least 0.06 apart and the lightest step at least 2:1 against the surface;
  8. the countermeasure matrix has one row per roadway pattern of either
     pre-registered list (the primary top-20 without its two daylight-with-time
     pairs, and the roadway top-20) and follows the eight mapping rules written in
     dashboard/README.md (--write-countermeasures regenerates it from those rules).

Standard library only; no database needed.

    python tests/check_dashboard_spec.py
    python tests/check_dashboard_spec.py --write-countermeasures

Exit code 0 when every check passes.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "dashboard"
EVIDENCE = ROOT / "docs" / "evidence" / "week11"
PROFILE = ROOT / "docs" / "profile"

STAGES = ["context", "finding", "action"]
TASKS = {"T1", "T2", "T3", "T4"}

# The design (section 3.1) derives each chart form from the comparison it supports.
FORMS_FOR_COMPARISON = {
    "part_to_whole_over_time": {"stacked_columns"},
    "magnitude_by_geography": {"choropleth_plus_ranked_bars"},
    "share_per_category": {"horizontal_bars"},
    "predicted_vs_observed_per_item": {"dumbbell_with_interval"},
    "method_vs_method": {"stat_tiles"},
    "item_by_time": {"heat_table"},
    "two_groups_per_item": {"dumbbell_two_groups"},
    "entity_vs_reference_per_item": {"dot_plot_with_reference"},
    "lookup": {"matrix_table"},
}

# Words that may not appear in a title or in alternative text (design, section 1.3).
FORBIDDEN = ["most dangerous", "risk", "prevent", "cause"]

REQUIRED_VIEW_COLUMNS = [
    "view_id", "order", "stage", "core", "tasks", "title", "question", "comparison_type",
    "chart_form", "source_fields", "comparison", "annotation", "uncertainty_shown",
    "limitation_ids", "controls", "alt_text",
]

# The eight FHWA proven-countermeasure families of the matrix, in column order.
FAMILIES = ["lighting", "crosswalk_visibility", "phb_rrfb", "medians_refuge",
            "road_diet", "speed_management", "lpi", "walkways"]
ARTERIALS = {"principal arterial", "minor arterial"}
HIGH_SPEED = {"45-50 mph", "55 mph or more"}
INTERSECTION = {"at intersection", "intersection-related"}


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, ok: bool, message: str) -> None:
        print(("  PASS  " if ok else "  FAIL  ") + message)
        if not ok:
            self.failures.append(message)

    def note(self, message: str) -> None:
        print("  note  " + message)


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


# ---------------------------------------------------------------- SQL parsing
def strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def split_top_level(text: str, sep: str = ",") -> list[str]:
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p for p in parts if p.strip()]


def view_columns(sql_path: Path) -> dict[str, set[str]]:
    """Column names of every view: the alias after AS, or the last dotted part."""
    sql = strip_sql_comments(sql_path.read_text(encoding="utf-8"))
    views: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE VIEW\s+(\w+)\s+AS(.*?);", sql, re.S | re.I):
        name, body = m.group(1), m.group(2)
        # the main SELECT is the one at parenthesis depth 0 (CTEs sit inside parentheses)
        depth, select_at, from_at = 0, None, None
        for t in re.finditer(r"\(|\)|\bSELECT\b|\bFROM\b", body, re.I):
            tok = t.group(0)
            if tok == "(":
                depth += 1
            elif tok == ")":
                depth -= 1
            elif depth == 0 and tok.upper() == "SELECT" and select_at is None:
                select_at = t.end()
            elif depth == 0 and tok.upper() == "FROM" and select_at is not None:
                from_at = t.start()
                break
        cols = set()
        for expr in split_top_level(body[select_at:from_at]):
            expr = " ".join(expr.split())
            alias = re.search(r"\bAS\s+(\w+)\s*$", expr, re.I)
            if alias:
                cols.add(alias.group(1).lower())
            else:
                cols.add(expr.split(".")[-1].strip().lower())
        views[name.lower()] = cols
    return views


def table_columns(schema_path: Path) -> dict[str, set[str]]:
    sql = strip_sql_comments(schema_path.read_text(encoding="utf-8"))
    tables: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE\s+(\w+)\s*\((.*?)\);", sql, re.S | re.I):
        cols = set()
        for line in split_top_level(m.group(2)):
            first = line.strip().split()[0] if line.strip() else ""
            if first and first.upper() not in {"CONSTRAINT", "PRIMARY", "FOREIGN", "CHECK", "UNIQUE", "EXCLUDE"}:
                cols.add(first.lower())
        tables[m.group(1).lower()] = cols
    return tables


# ------------------------------------------------------------ source fields
class Sources:
    def __init__(self) -> None:
        self.views = view_columns(ROOT / "sql" / "04_views.sql")
        self.tables = table_columns(ROOT / "sql" / "01_schema.sql")
        self.csv_dirs = [EVIDENCE, PROFILE, DASH]
        with open(EVIDENCE / "results_summary.json", encoding="utf-8") as f:
            self.summary = json.load(f)

    def csv_header(self, file_name: str) -> list[str] | None:
        for d in self.csv_dirs:
            p = d / file_name
            if p.exists():
                with open(p, newline="", encoding="utf-8") as f:
                    return next(csv.reader(f))
        return None

    def json_path_exists(self, path: str) -> bool:
        node = self.summary
        parts = path.split(".")
        for i, part in enumerate(parts):
            if part == "*":
                return i == len(parts) - 1 and isinstance(node, dict)
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    def exists(self, ref: str) -> tuple[bool, str]:
        """A reference is  v_view.column | table.column | file.csv:column | file.json:key.path"""
        if ":" in ref:
            file_name, member = ref.split(":", 1)
            if file_name.endswith(".json"):
                return self.json_path_exists(member), f"{file_name} has key path {member}"
            header = self.csv_header(file_name)
            if header is None:
                return False, f"{file_name} not found under docs/evidence/week11, docs/profile or dashboard"
            return member in header, f"{file_name} has column {member}"
        if "." in ref:
            owner, column = ref.rsplit(".", 1)
            owner, column = owner.lower(), column.lower()
            if owner in self.views:
                return column in self.views[owner], f"view {owner} has column {column}"
            if owner in self.tables:
                return column in self.tables[owner], f"table {owner} has column {column}"
            return False, f"{owner} is neither a view in 04_views.sql nor a table in 01_schema.sql"
        return False, f"unreadable source reference {ref!r}"


# ------------------------------------------------------------ color math
def linear_rgb(hex_color: str) -> list[float]:
    h = hex_color.strip().lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]


def relative_luminance(hex_color: str) -> float:
    r, g, b = linear_rgb(hex_color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG 2 luminance contrast ratio."""
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Machado, Oliveira & Fernandes (2009) colour-vision-deficiency transforms, severity 1.0, on linear RGB.
MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
}


def simulate(rgb: list[float], kind: str) -> list[float]:
    m = MACHADO[kind]
    return [min(1.0, max(0.0, sum(m[i][j] * rgb[j] for j in range(3)))) for i in range(3)]


def oklab(rgb: list[float]) -> tuple[float, float, float]:
    r, g, b = rgb
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def delta_e(a: str, b: str, kind: str | None = None) -> float:
    """Euclidean distance in OKLab x100, under simulated CVD when kind is given."""
    ra, rb = linear_rgb(a), linear_rgb(b)
    if kind:
        ra, rb = simulate(ra, kind), simulate(rb, kind)
    return 100 * math.dist(oklab(ra), oklab(rb))


def oklch_l_c_h(hex_color: str) -> tuple[float, float, float]:
    L, a, b = oklab(linear_rgb(hex_color))
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


L_BAND = (0.43, 0.77)      # OKLCH lightness band for series colors on a light surface
CHROMA_FLOOR = 0.10        # below it a hue reads as gray
CVD_FLOOR, NORMAL_FLOOR = 8.0, 15.0
RAMP_MIN_DL, RAMP_LIGHT_END = 0.06, 2.0


# --------------------------------------------------------- countermeasures
def parse_itemset(itemset: str) -> dict[str, str]:
    items = {}
    for part in itemset.split(" & "):
        var, value = part.split("=", 1)
        items[var.strip()] = value.strip()
    return items


def families_for(items: dict[str, str]) -> dict[str, int]:
    """The eight mapping rules of dashboard/README.md, one per family."""
    road, speed, light = items.get("road_class"), items.get("speed_bin"), items.get("light")
    crossing = items.get("crossing_location")
    has_intersection_item = crossing in INTERSECTION
    arterial_or_fast = road in ARTERIALS or speed in HIGH_SPEED
    return {
        "lighting": int(light == "dark, not lighted"),
        "crosswalk_visibility": int(crossing in INTERSECTION | {"not at intersection"}
                                    or road == "local road" or speed == "30 mph or less"),
        "phb_rrfb": int(crossing == "not at intersection"
                        or ((road in ARTERIALS or speed in {"35-40 mph", "45-50 mph"})
                            and crossing is None)),
        "medians_refuge": int(arterial_or_fast and not has_intersection_item),
        "road_diet": int(road in ARTERIALS and speed in {"35-40 mph", "45-50 mph"}),
        "speed_management": int(speed in HIGH_SPEED),
        "lpi": int(has_intersection_item),
        "walkways": int(road in {"local road", "collector"} or speed == "30 mph or less"),
    }


MATRIX_COLUMNS = ["primary_rank", "roadway_rank", "itemset", *FAMILIES]


def expected_matrix() -> list[dict[str, str]]:
    """One row per roadway pattern of either pre-registered list, in primary-rank order
    (patterns only on the roadway list follow, in roadway-rank order)."""
    primary = {p["itemset"]: p["rank"] for p in read_csv(EVIDENCE / "patterns_topk.csv")
               if p["expected_by_construction"].strip().lower() != "true"}
    roadway = {p["itemset"]: p["rank"] for p in read_csv(EVIDENCE / "patterns_topk_roadway.csv")}
    ordered = list(primary) + [it for it in roadway if it not in primary]
    rows = []
    for itemset in ordered:
        row = {"primary_rank": primary.get(itemset, ""), "roadway_rank": roadway.get(itemset, ""), "itemset": itemset}
        row.update({k: str(v) for k, v in families_for(parse_itemset(itemset)).items()})
        rows.append(row)
    return rows


def write_matrix(rows: list[dict[str, str]]) -> None:
    path = DASH / "countermeasures.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MATRIX_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


# --------------------------------------------------------------------- main
def run() -> Report:
    r = Report()
    views = read_csv(DASH / "views.csv")
    limitations = read_csv(DASH / "limitations.csv")
    palette = read_csv(DASH / "palette.csv")
    matrix = read_csv(DASH / "countermeasures.csv")
    sources = Sources()

    print("Structure of dashboard/views.csv")
    missing_cols = [c for c in REQUIRED_VIEW_COLUMNS if views and c not in views[0]]
    r.check(not missing_cols, f"all required columns present ({len(REQUIRED_VIEW_COLUMNS)})"
            + (f"; missing {missing_cols}" if missing_cols else ""))
    if missing_cols:
        return r
    ids = [v["view_id"] for v in views]
    r.check(len(ids) == len(set(ids)), f"{len(ids)} views with unique ids: {', '.join(ids)}")
    empty = [(v["view_id"], c) for v in views for c in REQUIRED_VIEW_COLUMNS if not v[c].strip()]
    r.check(not empty, "no required cell is empty" + (f"; empty: {empty}" if empty else ""))

    print("1. Every view supports an audience task")
    task_cover: dict[str, list[str]] = {t: [] for t in sorted(TASKS)}
    for v in views:
        tasks = split_list(v["tasks"])
        bad = [t for t in tasks if t not in TASKS]
        r.check(bool(tasks) and not bad, f"{v['view_id']} names tasks {tasks}")
        for t in tasks:
            if t in task_cover:
                task_cover[t].append(v["view_id"])
    for t, vs in task_cover.items():
        r.check(bool(vs), f"task {t} is served by {vs}")

    print("2. Chart forms match the comparisons")
    for v in views:
        allowed = FORMS_FOR_COMPARISON.get(v["comparison_type"])
        ok = allowed is not None and v["chart_form"] in allowed
        r.check(ok, f"{v['view_id']}: comparison '{v['comparison_type']}' -> form '{v['chart_form']}'"
                + ("" if ok else f" (allowed: {sorted(allowed) if allowed else 'unknown comparison'})"))

    print("3. The sequence provides context before conclusions")
    ordered = sorted(views, key=lambda v: int(v["order"]))
    stage_seq = [v["stage"] for v in ordered]
    r.check(all(s in STAGES for s in stage_seq), f"stages are among {STAGES}")
    ranks = [STAGES.index(s) for s in stage_seq if s in STAGES]
    r.check(ranks == sorted(ranks), "views run context -> finding -> action in display order: "
            + " ".join(f"{v['view_id']}({v['stage'][0]})" for v in ordered))
    r.check(bool(stage_seq) and stage_seq[0] == "context", "the first view is a context view")
    r.check(set(stage_seq) == set(STAGES), "every stage has at least one view")
    orders = [int(v["order"]) for v in views]
    r.check(sorted(orders) == list(range(1, len(views) + 1)), "display order is 1..N without gaps")

    print("4. Uncertainty and limitations appear beside the findings")
    lim_ids = {l["id"] for l in limitations}
    placed: dict[str, list[str]] = {l: [] for l in lim_ids}
    for v in views:
        refs = split_list(v["limitation_ids"])
        unknown = [x for x in refs if x not in lim_ids]
        r.check(not unknown, f"{v['view_id']} limitation ids exist {refs}")
        for x in refs:
            if x in placed:
                placed[x].append(v["view_id"])
        if v["stage"] in ("finding", "action"):
            r.check(bool(v["uncertainty_shown"].strip()), f"{v['view_id']} names the uncertainty element drawn beside it")
            r.check(bool(refs), f"{v['view_id']} carries at least one limitation block")
    for lid in sorted(lim_ids):
        r.check(bool(placed[lid]), f"limitation {lid} is placed beside {placed[lid]}")
    for l in limitations:
        n = len(l["text"].split())
        r.check(n <= 40, f"limitation {l['id']} is {n} words (limit 40)")

    print("5. Alternative text and forbidden claims")
    for v in views:
        alt = v["alt_text"].strip()
        r.check(bool(alt) and len(alt) <= 400, f"{v['view_id']} has alt text ({len(alt)} characters, limit 400)")
        hits = [w for w in FORBIDDEN if re.search(rf"\b{re.escape(w)}", (v["title"] + " " + alt).lower())]
        r.check(not hits, f"{v['view_id']} title and alt text avoid {FORBIDDEN}" + (f"; found {hits}" if hits else ""))

    print("6. Source fields exist in the SQL views, the schema or the evidence files")
    for v in views:
        for ref in split_list(v["source_fields"]):
            ok, why = sources.exists(ref)
            r.check(ok, f"{v['view_id']}: {why}")

    print("7. Palette contrast (WCAG 2 luminance ratio)")
    for p in palette:
        ratio = contrast(p["foreground"], p["background"])
        need = float(p["min_ratio"])
        ok = ratio >= need
        if ok:
            r.check(True, f"{p['pair']}: {ratio:.2f}:1 >= {need}:1")
        elif p["mitigation"].strip():
            r.check(True, f"{p['pair']}: {ratio:.2f}:1 < {need}:1, mitigated: {p['mitigation']}")
        else:
            r.check(False, f"{p['pair']}: {ratio:.2f}:1 < {need}:1 and no mitigation named")
    for p in palette:
        stated = p.get("stated_ratio", "").strip()
        if stated:
            ratio = contrast(p["foreground"], p["background"])
            r.check(abs(ratio - float(stated)) < 0.01, f"{p['pair']}: the design quotes {stated}:1, computed {ratio:.2f}:1")

    print("7b. Palette structure: series colors under colour-vision deficiency, and the ramps")
    roles = read_csv(DASH / "palette_roles.csv")
    surface = next(x["hex"] for x in roles if x["kind"] == "surface")
    series = [x for x in roles if x["kind"] == "series"]
    for x in series:
        L, C, _ = oklch_l_c_h(x["hex"])
        r.check(L_BAND[0] <= L <= L_BAND[1], f"{x['hex']} lightness L = {L:.2f} within {L_BAND}")
        r.check(C >= CHROMA_FLOOR, f"{x['hex']} chroma C = {C:.3f} >= {CHROMA_FLOOR}")
    for x, y in combinations(series, 2):
        cvd = min(delta_e(x["hex"], y["hex"], "protan"), delta_e(x["hex"], y["hex"], "deutan"))
        normal = delta_e(x["hex"], y["hex"])
        r.check(cvd >= CVD_FLOOR, f"{x['hex']} vs {y['hex']}: CVD separation dE = {cvd:.1f} (protan/deutan, OKLab x100) >= {CVD_FLOOR}")
        r.check(normal >= NORMAL_FLOOR, f"{x['hex']} vs {y['hex']}: normal-vision separation dE = {normal:.1f} >= {NORMAL_FLOOR}")
    gray = next(x for x in roles if x["kind"] == "context")
    r.check(oklch_l_c_h(gray["hex"])[1] < CHROMA_FLOOR,
            f"context gray {gray['hex']} is below the chroma floor (reads as gray, not as a third series)")
    for kind in ("ramp_map", "ramp_heat"):
        steps = [x["hex"] for x in roles if x["kind"] == kind]
        Ls = [oklch_l_c_h(h)[0] for h in steps]
        hues = [oklch_l_c_h(h)[2] for h in steps]
        r.check(all(Ls[i] > Ls[i + 1] for i in range(len(Ls) - 1)), f"{kind}: lightness falls monotonically {[round(v, 2) for v in Ls]}")
        r.check(all(Ls[i] - Ls[i + 1] >= RAMP_MIN_DL for i in range(len(Ls) - 1)), f"{kind}: every adjacent step differs by >= {RAMP_MIN_DL} in lightness")
        r.check(contrast(steps[0], surface) >= RAMP_LIGHT_END, f"{kind}: lightest step {steps[0]} is {contrast(steps[0], surface):.2f}:1 against the surface (>= {RAMP_LIGHT_END}:1)")
        r.check(max(hues) - min(hues) <= 10, f"{kind}: one hue (spread {max(hues) - min(hues):.1f} degrees)")

    print("8. Countermeasure matrix covers the roadway patterns and follows the rules")
    expected = expected_matrix()
    r.check([m["itemset"] for m in matrix] == [e["itemset"] for e in expected],
            f"one row per roadway pattern of either pre-registered list, in order ({len(expected)} rows)")
    r.check(list(matrix[0].keys()) == MATRIX_COLUMNS if matrix else False,
            "columns are primary_rank, roadway_rank, itemset and the eight families")
    by_itemset = {m["itemset"]: m for m in matrix}
    for e in expected:
        m = by_itemset.get(e["itemset"])
        label = f"primary #{e['primary_rank']}" if e["primary_rank"] else f"roadway #{e['roadway_rank']}"
        same = m is not None and all(m.get(c) == e[c] for c in MATRIX_COLUMNS)
        r.check(same, f"{label} matches the mapping rules and both ranks")
        r.check(m is not None and any(m.get(f) == "1" for f in FAMILIES), f"{label} has at least one family")
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-countermeasures", action="store_true",
                    help="regenerate dashboard/countermeasures.csv from the mapping rules, then check")
    args = ap.parse_args()
    if args.write_countermeasures:
        write_matrix(expected_matrix())
    report = run()
    print()
    if report.failures:
        print(f"{len(report.failures)} check(s) failed.")
        sys.exit(1)
    print("All checks passed: the dashboard specification is consistent with the repository.")


if __name__ == "__main__":
    main()
