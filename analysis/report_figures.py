"""Static figures for the Week 13 technical report draft.

Reads only committed, aggregate evidence files (no person-level rows) and writes PNGs to
docs/figures/week13/. Colours are the Week 12 dashboard palette (dashboard/palette_roles.csv):
blue = 2020-2023 (the prediction), orange = 2024 (held out, provisional), gray = context/baseline.

Usage (from the repository root):
    python analysis/report_figures.py

Needs matplotlib (not in requirements.txt, because the pipeline and the experiment do not use it).
"""
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "docs" / "evidence" / "week11"
OUT = ROOT / "docs" / "figures" / "week13"

BLUE, ORANGE, GRAY, NAVY = "#2a78d6", "#eb6834", "#898781", "#0d366b"
INK, INK2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e2dd"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
})

SHORT = {
    "55 mph or more": "≥55 mph", "30 mph or less": "≤30 mph",
    "35-40 mph": "35–40 mph", "45-50 mph": "45–50 mph",
    "midday (10-15)": "midday 10–15", "morning (6-9)": "morning 6–9",
    "evening (16-19)": "evening 16–19", "night (20-23)": "night 20–23",
    "late night (0-5)": "late night 0–5",
}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def label(itemset):
    parts = [p.split("=", 1)[1] for p in itemset.split(" & ")]
    return " · ".join(SHORT.get(p, p) for p in parts)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=200)
    plt.close(fig)
    print("wrote", (OUT / name).relative_to(ROOT))


def fig_deaths_by_year():
    # Source: docs/profile/02_unit_of_observation.csv (Week 6 profile of the raw files).
    years = [2020, 2021, 2022, 2023, 2024]
    total = [695, 819, 780, 774, 668]
    scope = [588, 674, 644, 625, 522]
    fig, ax = plt.subplots(figsize=(6.6, 3.3))
    for x, (yr, t, s) in enumerate(zip(years, total, scope)):
        ax.bar(x, s, width=0.62, color=ORANGE if yr == 2024 else BLUE, edgecolor=SURFACE, linewidth=1.5)
        ax.bar(x, t - s, bottom=s, width=0.62, color=GRAY, edgecolor=SURFACE, linewidth=1.5)
        ax.text(x, s / 2, f"{s}\nin scope", ha="center", va="center", fontsize=8, color=INK)
        ax.text(x, t + 10, f"{t} deaths", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(5))
    ax.set_xticklabels(["2020", "2021", "2022", "2023", "2024\n(provisional)"])
    ax.set_ylim(0, 900)
    ax.set_ylabel("pedestrian deaths in Florida")
    ax.yaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", length=0)
    fig.legend(handles=[
        Patch(color=BLUE, label="in scope (urban, non-freeway), 2020–2023 Final files"),
        Patch(color=ORANGE, label="in scope, 2024 Annual Report File (held-out test year)"),
        Patch(color=GRAY, label="out of scope: rural, freeway or interstate, or urban/rural not coded"),
    ], loc="upper left", bbox_to_anchor=(0.09, 0.995), fontsize=7.5, handlelength=1.2)
    fig.subplots_adjust(left=0.1, right=0.98, top=0.8, bottom=0.14)
    save(fig, "fig1_deaths_by_year.png")


def pattern_axis(ax, rows, extra_tags=True):
    labels = []
    for r in rows:
        tag = ""
        if extra_tags and r.get("expected_by_construction") == "True":
            tag += "  †"
        if extra_tags and r.get("replicated", "True") != "True":
            tag += "  ×"
        labels.append(f'{r["rank"]}.  {label(r["itemset"])}{tag}')
    n = len(rows)
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_ylim(n - 0.4, -1.3)
    ax.xaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("share of in-scope pedestrian deaths (%)")


def fig_patterns_2024():
    rows = read_csv(EV / "patterns_topk.csv")
    fig, ax = plt.subplots(figsize=(7.6, 6.4))
    for i, r in enumerate(rows):
        fit, base, obs = (100 * float(r[k]) for k in ("fit_support", "baseline_support", "obs_support"))
        lo, hi = 100 * float(r["obs_wilson_low"]), 100 * float(r["obs_wilson_high"])
        ax.plot([lo, hi], [i, i], color=ORANGE, lw=1.4, solid_capstyle="round", zorder=2)
        ax.plot(base, i, marker="|", color=GRAY, ms=9, mew=1.8, ls="none", zorder=3)
        ax.plot(fit, i, marker="o", color=BLUE, ms=6.5, mec=SURFACE, mew=1.2, ls="none", zorder=4)
        ax.plot(obs, i, marker="D", color=ORANGE, ms=5.5, mec=SURFACE, mew=1.2, ls="none", zorder=5)
    ax.axvline(3, color=INK2, lw=0.8, ls=(0, (3, 3)), zorder=1)
    ax.text(3.12, -0.78, "3% support floor", ha="left", va="center", fontsize=7, color=INK2)
    pattern_axis(ax, rows)
    ax.set_xlim(0, 11.5)
    fig.legend(handles=[
        Line2D([], [], marker="o", color=BLUE, ls="none", ms=6.5, mec=SURFACE, mew=1.2,
               label="2020–2023 share = the pattern's prediction for 2024"),
        Line2D([], [], marker="D", color=ORANGE, ls="-", lw=1.4, ms=5.5, mec=SURFACE, mew=1.2,
               label="2024 observed share with Wilson 95% interval (provisional file)"),
        Line2D([], [], marker="|", color=GRAY, ls="none", ms=9, mew=1.8,
               label="independence baseline prediction (product of single-condition shares)"),
    ], loc="upper left", bbox_to_anchor=(0.01, 0.998), fontsize=7.5)
    fig.text(0.99, 0.985, "†  true by construction (daylight and time of day)\n×  did not replicate in 2024",
             ha="right", va="top", fontsize=7, color=INK2)
    fig.subplots_adjust(left=0.54, right=0.985, top=0.895, bottom=0.075)
    save(fig, "fig5_patterns_predicted_vs_2024.png")


def fig_mae():
    s = json.loads((EV / "results_summary.json").read_text(encoding="utf-8"))
    lists = [("Top 20 (primary)", s["results"]["top_20"]), ("Top 10", s["results"]["top_10"]),
             ("Roadway top 20 (secondary)", s["roadway_topk"]["top_20"]),
             ("Roadway top 10 (secondary)", s["roadway_topk"]["top_10"])]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    for i, (_, d) in enumerate(lists):
        for key, col, mk, dy in (("candidate", BLUE, "o", -0.17), ("baseline", GRAY, "s", 0.17)):
            v = d[f"mae_pp_{key}"]
            lo, hi = d["ci95"][f"mae_pp_{key}"]
            ax.plot([lo, hi], [i + dy, i + dy], color=col, lw=1.6, solid_capstyle="round", zorder=2)
            ax.plot(v, i + dy, marker=mk, color=col, ms=6.5, mec=SURFACE, mew=1.2, ls="none", zorder=3)
            ax.text(hi + 0.06, i + dy, f"{v:.2f}", va="center", ha="left", fontsize=7.5, color=INK)
    ax.set_yticks(range(len(lists)))
    ax.set_yticklabels([n for n, _ in lists])
    ax.set_ylim(len(lists) - 0.45, -0.55)
    ax.set_xlim(0, 4.4)
    ax.set_xlabel("mean absolute error between predicted and observed 2024 share\n(percentage points of deaths; lower is better)")
    ax.xaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    fig.legend(handles=[
        Line2D([], [], marker="o", color=BLUE, ls="-", lw=1.6, ms=6.5, mec=SURFACE, mew=1.2,
               label="candidate: mined patterns (2020–2023 share), 95% cluster-bootstrap interval"),
        Line2D([], [], marker="s", color=GRAY, ls="-", lw=1.6, ms=6.5, mec=SURFACE, mew=1.2,
               label="baseline: statistical independence"),
    ], loc="upper left", bbox_to_anchor=(0.01, 0.998), fontsize=7.5)
    fig.subplots_adjust(left=0.27, right=0.98, top=0.82, bottom=0.21)
    save(fig, "fig4_mae_candidate_vs_baseline.png")


def fig_county_split():
    rows = read_csv(EV / "subgroup_county.csv")
    big = [r for r in rows if r["group"] == "five most populous"]
    rest = {r["pattern_rank"]: r for r in rows if r["group"] == "other counties"}
    for r in big:
        r["rank"] = r["pattern_rank"]
    fig, ax = plt.subplots(figsize=(7.6, 6.2))
    for i, r in enumerate(big):
        a = 100 * float(r["observed_support"])
        b = 100 * float(rest[r["pattern_rank"]]["observed_support"])
        pred = 100 * float(r["predicted_candidate"])
        ax.plot([a, b], [i, i], color=NAVY, lw=1.0, zorder=2)
        ax.plot(pred, i, marker="|", color=GRAY, ms=9, mew=1.8, ls="none", zorder=3)
        ax.plot(b, i, marker="o", color=SURFACE, ms=6.5, mec=NAVY, mew=1.4, ls="none", zorder=4)
        ax.plot(a, i, marker="o", color=NAVY, ms=6.5, mec=SURFACE, mew=1.0, ls="none", zorder=5)
    pattern_axis(ax, big, extra_tags=False)
    ax.set_xlim(0, 11.5)
    ax.set_xlabel("share of the group's 2024 in-scope pedestrian deaths (%)")
    fig.legend(handles=[
        Line2D([], [], marker="o", color=NAVY, ls="none", ms=6.5, mec=SURFACE, mew=1.0,
               label="five most populous counties (233 deaths in 2024)"),
        Line2D([], [], marker="o", color=SURFACE, ls="none", ms=6.5, mec=NAVY, mew=1.4,
               label="other 62 counties (289 deaths in 2024)"),
        Line2D([], [], marker="|", color=GRAY, ls="none", ms=9, mew=1.8,
               label="statewide 2020–2023 share (the prediction)"),
    ], loc="upper left", bbox_to_anchor=(0.01, 0.998), fontsize=7.5)
    fig.subplots_adjust(left=0.54, right=0.985, top=0.895, bottom=0.075)
    save(fig, "fig6_county_split_2024.png")


if __name__ == "__main__":
    fig_deaths_by_year()
    fig_patterns_2024()
    fig_mae()
    fig_county_split()
