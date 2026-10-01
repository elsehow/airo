"""Stacked incident-severity panels with readable death/damage tick labels.

Uses the dashboard's graph2_data.json medians; stacking horizons leaves
enough horizontal room for all eight paired severity labels at paper size.
"""
from __future__ import annotations

from . import style
from .dates import month_year
from .style import FULL_W, INK


def render(blob: dict):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, NullFormatter

    horizons = ("2030", "2050", "2100")
    fig, axes = plt.subplots(3, 1, figsize=(FULL_W, 5.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.87, bottom=0.17, hspace=0.28)
    causes = ("cyber", "misalign", "bio")
    # The rungs every plotted cause answered at every horizon: the extinction
    # rung (2026-09-16) is absent from runs before it and never plotted then.
    answered = set.intersection(*[
        {r["rung"] for c in blob["byHorizon"][h]["causes"] if c["key"] == cause for r in c["rungs"]}
        for h in horizons for cause in causes])
    rungs = [r for r in blob["rungs"] if r["rung"] in answered]
    xs = list(range(len(rungs)))
    names = {"cyber": "Cyber", "misalign": "Misalignment", "bio": "Human-caused epidemic"}
    patterns = {"cyber": "-", "misalign": "--", "bio": ":"}
    values = []
    for ax, horizon in zip(axes, horizons):
        cells = {c["key"]: c for c in blob["byHorizon"][horizon]["causes"]}
        for cause in causes:
            cell = cells[cause]
            medians = {r["rung"]: r["median"] for r in cell["rungs"]}
            ys = [medians[r["rung"]] for r in rungs]
            if any(y is None or y <= 0 for y in ys):
                raise ValueError("Incident ladder log plot needs complete positive medians; zero probabilities require an explicit treatment.")
            values.extend(ys)
            ax.plot(xs, ys, marker="o", markersize=2.5, linestyle=patterns[cause],
                    color=cell["color"], label=names[cause])
        ax.set_yscale("log")
        windows = (blob.get("instrumentInfo", {}).get("countingWindows", {}).get(horizon) or [])
        title = f"By {horizon}"
        if windows:
            title += " · onsets " + "; ".join(
                f"{month_year(w['start'])} to {month_year(w['end'])}" for w in windows)
        ax.set_title(title, fontsize=8, color=INK, pad=3)
        ax.grid(True, axis="y")
        ax.set_axisbelow(True)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: style.esc(f"{v:g}%")))
        ax.yaxis.set_minor_formatter(NullFormatter())
    axes[0].set_ylim(min(values) / 1.5, 150)
    axes[-1].set_xticks(xs)
    # The blob's own labels supply the paired dollar amounts, including units;
    # the extinction rung (2026-09-16) has no dollar leg and says so.
    def _tick(r):
        lower = r["label"].split(" or ", 1)[1] if " or " in r["label"] else "no dollar leg"
        upper = "Extinction" if r.get("damages") is None else r["rung"]
        return style.esc(f"{upper}\n{lower}").replace(
            "$", r"\textdollar{}" if style.backend() == "pgf" else "$")
    axes[-1].set_xticklabels([_tick(r) for r in rungs])
    axes[-1].set_xlabel("Severity: deaths or equivalent morbidity (upper)\n"
                        "or economic damages in 2026 dollars (lower)", labelpad=7)
    fig.text(0.015, 0.55, "Probability of reaching the threshold (log scale)",
             rotation=90, ha="center", va="center", fontsize=8, color=INK)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.54, 1.0))
    fig.text(0.54, 0.94, f"Median of {len(blob['models'])} models. Cumulative incidents; harm within 3 years after onset.",
             ha="center", fontsize=7, color=INK)
    return fig
