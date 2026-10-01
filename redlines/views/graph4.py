"""Graph 4 (two-sim ECI panel): blob builder.

Ported from code/make_demo_combined.py -- the lead author's original Graph-4 design
(per-model calibration curves + Brier skill), fed the TWO-SIM AVERAGE. For
each model, pools its forecasts from BOTH simulators, weighting each
simulator EQUALLY (so it's an average, not a count-weighted pool):
  - CivBench (FreeCiv): H2-H4 horizon x 5-9% base-rate subset of the full eval.
  - Starsim pandemic: the deaths-threshold smoke (per-question preds).
Where only one simulator scored a model, that one is used.

Pure: build() takes already-resolved input paths and returns the blob dict --
no argparse, no file writes, no hydration (the code/make_demo_combined.py
shim does all three, preserving R0's rewire to redlines.hydrate.inject).
"""
from __future__ import annotations

import json
import statistics

from ..config import CLIM_FREECIV_COMBINED, FC_BAND, FC_HORIZONS, PAN_MIN_N
from ..registry import CONFOUNDED_ARCHITECTURES, MODELS, color_for, demo_set_with_eci, published_panel
from ..stats import brier_mean, bss, deciles_weighted, spearman

# litellm_id -> architecture, for joining onto demo_set_with_eci()'s rows
# (which don't carry architecture -- their dict shape is pinned elsewhere).
_ARCH_BY_ID = {m["litellm_id"]: m["architecture"] for m in MODELS}
_ROW_BY_ID = {m["litellm_id"]: m for m in MODELS}


def freeciv_pairs(eval_path, questions_path):
    """label -> list of (pred, obs, clim) on the CivBench near-term tail-risk subset.

    Source: code/make_demo_combined.py::freeciv_pairs.

    The corpus key is (game_id, question_id), NOT question_id alone. A
    question_id is a per-game index: the 25,919 corpus instances carry only
    336 distinct ids, and 246 of those 336 name a different (template,
    target, resolution turn) in different games. Keying on the id alone made
    the dict last-wins, so each eval row was filtered -- and given its BSS
    climatology -- from an unrelated game's question. See the commit message
    for the size of the error this replaced.
    """
    results = json.load(open(eval_path))["results"]
    qm = {(q["game_id"], q["question_id"]): q
          for q in json.load(open(questions_path))["questions"]}
    rows = []
    for r in results:
        q = qm.get((r.get("game_id"), r["question_id"]), {})
        # The corpus base rate, not the eval row's own: code/run_eval.py
        # stamped r["class_base_rate"] through the same broken join, so the
        # row's copy is wrong on 826 of 1,739 rows.
        br = q.get("class_base_rate", CLIM_FREECIV_COMBINED)
        if q.get("horizon") in FC_HORIZONS and FC_BAND[0] <= br < FC_BAND[1]:
            r["_br"] = br
            rows.append(r)
    out = {}
    for m in demo_set_with_eci(include_gap_fillers=True):
        mid = m["model_id"]
        pairs = []
        for r in rows:
            p = r.get("predictions", {}).get(mid, {}).get("probability")
            if p is None:
                continue
            pairs.append((p, 1.0 if r["ground_truth"] else 0.0, r["_br"]))
        if pairs:
            out[m["label"]] = pairs
    return out


def pandemic_pairs(preds_path):
    """label -> list of (pred, obs, clim) from the Starsim pandemic smoke.

    Source: code/make_demo_combined.py::pandemic_pairs.
    """
    doc = json.load(open(preds_path))
    return {m["label"]: [(p, y, c) for p, y, c in m["samples"]]
            for m in doc.values() if len(m["samples"]) >= PAN_MIN_N}


def combine(fc, pan):
    """Equal-weight per simulator -> weighted pairs (pred, obs, clim, w).

    Source: code/make_demo_combined.py::combine.
    """
    parts = []
    for src in (fc, pan):
        if src:
            w = 0.5 / len(src) if (fc and pan) else 1.0 / len(src)
            parts += [(p, o, c, w) for p, o, c in src]
    return parts


def ensemble_pairs(eval_path, questions_path, pandemic_preds_path, member_ids):
    """The PANEL ENSEMBLE's (pred, obs, clim) pairs on each simulator: per
    question, the median of the members' predictions (worklist C13,
    2026-09-02). CivBench rows are keyed, so any member present on a row
    contributes; Starsim samples are per-model lists that share one draw
    sequence, so members are pooled per index only where their (obs, clim)
    sequences are identical. A question needs at least two members.
    -> ({label: pairs} for the two sims as freeciv_pairs/pandemic_pairs
    give them, the members actually used on each)."""
    results = json.load(open(eval_path))["results"]
    qm = {(q["game_id"], q["question_id"]): q
          for q in json.load(open(questions_path))["questions"]}
    fc, used_fc = [], set()
    for r in results:
        q = qm.get((r.get("game_id"), r["question_id"]), {})
        br = q.get("class_base_rate", CLIM_FREECIV_COMBINED)
        if q.get("horizon") not in FC_HORIZONS or not (FC_BAND[0] <= br < FC_BAND[1]):
            continue
        ps = {mid: r.get("predictions", {}).get(mid, {}).get("probability") for mid in member_ids}
        ps = {k: v for k, v in ps.items() if v is not None}
        if len(ps) < 2:
            continue
        used_fc |= set(ps)
        fc.append((statistics.median(ps.values()), 1.0 if r["ground_truth"] else 0.0, br))
    doc = json.load(open(pandemic_preds_path))
    present = {mid: doc[mid]["samples"] for mid in member_ids
               if mid in doc and len(doc[mid]["samples"]) >= PAN_MIN_N}
    pan, used_pan = [], set()
    if len(present) >= 2:
        seqs = {mid: [(y, c) for _, y, c in smp] for mid, smp in present.items()}
        ref = next(iter(seqs.values()))
        aligned = {mid: present[mid] for mid, sq in seqs.items() if sq == ref}
        if len(aligned) >= 2:
            used_pan = set(aligned)
            for i, (_, y, c) in enumerate(ref and next(iter(aligned.values()))):
                pan.append((statistics.median(smp[i][0] for smp in aligned.values()), y, c))
    return fc, pan, sorted(used_fc), sorted(used_pan)


def bss_of(pairs):
    """Brier skill score of an (pred, obs, clim) triple list, or None if empty.

    Source: code/make_demo_combined.py::bss_of, rebuilt on top of
    redlines.stats.brier_mean/bss.
    """
    if not pairs:
        return None
    b = brier_mean([(p, o) for p, o, c in pairs])
    bc = brier_mean([(c, o) for p, o, c in pairs])
    return bss(b, bc)


def build(eval_path, questions_path, pandemic_preds_path, final=False):
    """Compute the Graph-4 two-sim ECI panel blob.

    Byte-exact port of code/make_demo_combined.py::main's blob assembly.
    Pure: no writes, no argparse, no hydration.
    """
    fc = freeciv_pairs(eval_path, questions_path)
    pan = pandemic_pairs(pandemic_preds_path)
    order = sorted(demo_set_with_eci(include_gap_fillers=True), key=lambda m: m["eci"])
    # The dashboard's panel (redlines.registry.panel): its members draw in
    # their registry colors, the same as on every other chart, and the rest
    # of the ladder in the one retired gray (project lead, 2026-09-08). Before, an
    # 11-step ECI ramp colored the ladder and the panel was an accent green.
    panel_ids = {row["litellm_id"] for row, _ in published_panel()}
    members = {row["key"] for row, _ in published_panel()}

    models_out, scatter, all_w = [], [], []
    for i, m in enumerate(order):
        lbl = m["label"]
        comb = combine(fc.get(lbl, []), pan.get(lbl, []))
        if not comb:
            continue
        wpairs = [(p, o, w) for p, o, c, w in comb]
        pts = deciles_weighted(wpairs)
        W = sum(w for _, _, _, w in comb)
        brier = sum(w * (p - o) ** 2 for p, o, c, w in comb) / W
        brier_clim = sum(w * (c - o) ** 2 for p, o, c, w in comb) / W
        entry_bss = bss(brier, brier_clim)
        mean_p = sum(w * p for p, o, c, w in comb) / W
        mean_o = sum(w * o for p, o, c, w in comb) / W
        color = color_for(_ROW_BY_ID[m["model_id"]], members)
        arch = _ARCH_BY_ID[m["model_id"]]
        excluded = arch in CONFOUNDED_ARCHITECTURES
        entry = {"key": m["model_id"], "label": lbl, "eci": m["eci"], "color": color,
                 "n": len(comb), "brier": round(brier, 4),
                 "bss": entry_bss,
                 "meanPred": round(mean_p, 4), "meanObs": round(mean_o, 4),
                 "sims": ("civbench+starsim" if (lbl in fc and lbl in pan) else ("civbench" if lbl in fc else "starsim")),
                 "pts": [{"pred": round(p["pred"], 5), "obs": round(p["obs"], 5), "n": p["n"]} for p in pts],
                 # TODO.md Phase 2: dense/MoE/distilled declared in data (see
                 # redlines/registry.py), so the clean-subset trend below is
                 # reproducible rather than hand-picked.
                 "architecture": arch, "excluded": excluded,
                 "inPanel": m["model_id"] in panel_ids}
        models_out.append(entry)
        scatter.append({"eci": m["eci"], "bss": entry["bss"], "label": lbl, "color": color,
                        "meanPred": entry["meanPred"], "meanObs": entry["meanObs"],
                        "bssCiv": bss_of(fc.get(lbl, [])), "bssStar": bss_of(pan.get(lbl, [])),
                        "architecture": arch, "excluded": excluded,
                        "inPanel": m["model_id"] in panel_ids})
        all_w += comb

    base = sum(w * o for p, o, c, w in all_w) / sum(w for p, o, c, w in all_w)
    max_pred = max(m["pts"][-1]["pred"] for m in models_out)
    domain_max = min(0.9, (int(max_pred / 0.05) + 1) * 0.05)

    rho = round(spearman([s["eci"] for s in scatter], [s["bss"] for s in scatter]), 2)

    # The panel ensemble (C13, 2026-09-02): the median of the panel's
    # predictions per question, scored like a model, drawn as its own mark
    # and kept OUT of rho and the model list -- it is not a point on the
    # capability ladder. Members are the panel models these benches ran;
    # GPT-5.5 Pro is on neither (docs/methodology.md), so it is three of four.
    ens_fc, ens_pan, used_fc, used_pan = ensemble_pairs(eval_path, questions_path, pandemic_preds_path,
                                                        sorted(panel_ids))
    ens_comb = combine(ens_fc, ens_pan)
    ensemble = None
    if ens_comb:
        W_e = sum(w for _, _, _, w in ens_comb)
        b_e = sum(w * (p - o) ** 2 for p, o, c, w in ens_comb) / W_e
        bc_e = sum(w * (c - o) ** 2 for p, o, c, w in ens_comb) / W_e
        by_id = {m["model_id"]: m for m in order}
        members = sorted(set(used_fc) | set(used_pan))
        ensemble = {
            "label": "Panel ensemble", "bss": bss(b_e, bc_e), "brier": round(b_e, 4),
            "n": len(ens_comb), "bssCiv": bss_of(ens_fc), "bssStar": bss_of(ens_pan),
            "meanPred": round(sum(w * p for p, o, c, w in ens_comb) / W_e, 4),
            "meanObs": round(sum(w * o for p, o, c, w in ens_comb) / W_e, 4),
            "members": [by_id[m]["label"] for m in members if m in by_id],
            "membersCiv": [by_id[m]["label"] for m in used_fc if m in by_id],
            "membersStar": [by_id[m]["label"] for m in used_pan if m in by_id],
            "absent": [row["label"] for row, _ in published_panel() if row["litellm_id"] not in members],
            # Drawn at the members' median ECI; the ensemble has no ECI of its own.
            "eci": statistics.median(by_id[m]["eci"] for m in members if m in by_id),
            "rule": "median of the members' probabilities per question; equal weight per simulator",
        }

    # Clean subset (TODO.md Phase 2): same trend statistic, computed only over
    # points whose architecture isn't a known confound. Always shown alongside
    # the full-set rho above -- never in place of it (see docs/methodology.md
    # "Graph 4 subsetting").
    clean = [s for s in scatter if not s["excluded"]]
    rho_clean = round(spearman([s["eci"] for s in clean], [s["bss"] for s in clean]), 2)

    blob = {"preliminary": not final, "world": "combined", "rho": rho,
            "bandLabel": "1–9%",
            "corpusLabel": "two-sim average (CivBench tail + Starsim pandemic)",
            "base": round(base, 4), "domainMax": round(domain_max, 3),
            "nModels": len(models_out), "nQuestions": sum(m["n"] for m in models_out),
            "models": models_out, "scatter": scatter,
            "ensemble": ensemble,
            # New keys (TODO.md Phase 2 -- Graph 4 credibility): existing keys
            # above are byte-unchanged. "rhoClean"/"nModelsClean" describe the
            # dense+undisclosed subset; "excludedArchitectures" documents the
            # rule that produced it (see registry.CONFOUNDED_ARCHITECTURES).
            "rhoClean": rho_clean, "nModelsClean": len(clean),
            "excludedArchitectures": sorted(CONFOUNDED_ARCHITECTURES)}
    return blob
