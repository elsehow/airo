"""The two conditional benches on the "Why trust this?" tab (Graphs 5 and 6):
the vendored datasets are intact, and the in-repo scorers reproduce the
numbers each bench published.

  * Causal (data/causal/): the locked dataset's MANIFEST.sha256 verifies, and
    redlines.views.causal recomputes the README's headline -- Spearman
    rho = +0.68, p = 0.0003, n = 23 -- from the locked CSV with stdlib only.
  * Observational (code/observational/, data/observational/): the view's
    scoring of the 2026-08-20 four-model run matches the table in
    code/observational/UPSTREAM-README.md (score_bench.py's output) metric
    for metric, and its roster-id mapping is total.
  * redlines.stats.spearman_ties / spearman_p agree with scipy's spearmanr
    on the figures the causal README quotes (computed once with scipy,
    pinned here).
"""
import hashlib
import unittest

from redlines.config import REPO_ROOT
from redlines.roster import ANTHROPIC_IDS, by_id, load
from redlines.stats import spearman_p, spearman_ties
from redlines.views import causal, observational

CAUSAL = REPO_ROOT / "data" / "causal"
OBS_RUN_2026_08_20 = REPO_ROOT / "results" / "observational" / "results_2026-08-20.jsonl"


class TestRoster(unittest.TestCase):
    def test_roster_loads_and_is_ranked(self):
        r = load()
        self.assertEqual(len(r), 32)   # the causal roster + Graph 4's eight others
        self.assertEqual(sum(m["source"] == "causal" for m in r), 24)
        self.assertEqual(sum(m["source"] == "g4" for m in r), 8)
        self.assertEqual([m["eci"] for m in r], sorted(m["eci"] for m in r))
        self.assertEqual(len({m["label"] for m in r}), 32)
        self.assertEqual(len({m["id"] for m in r}), 32)

    def test_graph4_ladder_is_covered(self):
        # Every model Graph 4 draws is on the roster under some OpenRouter id.
        from redlines.registry import MODELS
        labels = {m["label"] for m in load()}
        for m in MODELS:
            if {"g4_ladder", "g4_gapfiller"} & set(m["roles"]):
                self.assertIn(m["label"], labels, m["key"])

    def test_registry_labels_are_used(self):
        b = by_id()
        self.assertEqual(b["anthropic/claude-fable-5"]["label"], "Fable 5")
        self.assertEqual(b["openai/gpt-5.5"]["label"], "GPT-5.5")
        self.assertEqual(b["anthropic/claude-haiku-4.5"]["label"], "Haiku 4.5")
        self.assertEqual(b["meta-llama/llama-4-scout"]["label"], "Llama 4 Scout")

    def test_anthropic_ids_map_onto_the_roster(self):
        b = by_id()
        for v in ANTHROPIC_IDS.values():
            self.assertIn(v, b)


class TestCausalLockedDataset(unittest.TestCase):
    def test_manifest_verifies(self):
        manifest = (CAUSAL / "MANIFEST.sha256").read_text().splitlines()
        self.assertGreater(len(manifest), 10)
        for line in manifest:
            digest, rel = line.split("  ", 1)
            path = CAUSAL / rel.removeprefix("./")
            self.assertTrue(path.exists(), rel)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, rel)

    def test_headline_reproduces_the_readme(self):
        b = causal.build()
        h = b["headline"]
        self.assertEqual(h["n"], 23)
        self.assertEqual(round(h["rho"], 2), 0.68)
        self.assertEqual(round(h["p"], 4), 0.0003)
        self.assertEqual(round(h["baselineP"], 2), 0.21)
        self.assertEqual(round(h["perRung"]["50"]["rho"], 2), 0.70)
        self.assertEqual(round(h["perRung"]["25"]["rho"], 2), 0.53)
        self.assertEqual(round(h["perRung"]["90"]["rho"], 2), 0.41)
        self.assertEqual([e["id"] for e in b["excluded"]], ["deepseek/deepseek-v4-flash-0731"])
        self.assertEqual(b["best"]["label"], "GPT-5.5")

    def test_models_are_the_locked_csv(self):
        b = causal.build()
        fable = next(m for m in b["models"] if m["id"] == "anthropic/claude-fable-5")
        self.assertEqual(fable["recovered"], 0.6684)
        self.assertEqual(fable["eci"], 162.49)
        # inPanel follows the dashboard's panel (the newest run's); a member
        # draws in its registry color, everyone else in the one retired gray.
        from redlines.registry import MODELS, RETIRED_COLOR, published_panel
        panel_ids = {row["litellm_id"] for row, _ in published_panel()}
        by_id = {m["litellm_id"]: m for m in MODELS}
        for m in b["models"]:
            self.assertEqual(m["inPanel"], m["id"] in panel_ids, m["id"])
            self.assertEqual(m["color"], by_id[m["id"]]["color"] if m["id"] in panel_ids else RETIRED_COLOR, m["id"])
        self.assertEqual([m["eci"] for m in b["models"]], sorted(m["eci"] for m in b["models"]))


class TestStatsAgreeWithScipy(unittest.TestCase):
    def test_spearman_ties_and_p(self):
        # scipy.stats.spearmanr on data/causal/results/eci_vs_pooled.csv:
        # statistic=0.6808300395256918, pvalue=0.00034920400411918566
        import csv
        rows = list(csv.DictReader(open(CAUSAL / "results" / "eci_vs_pooled.csv")))
        xs = [float(r["eci"]) for r in rows]
        ys = [float(r["pooled_intervention_recovered"]) for r in rows]
        rho = spearman_ties(xs, ys)
        self.assertAlmostEqual(rho, 0.6808300395256918, places=12)
        self.assertAlmostEqual(spearman_p(rho, len(xs)), 0.00034920400411918566, places=12)

    def test_ties_get_average_ranks(self):
        # x strictly increasing; y has a three-way tie at the bottom: ranks
        # [2, 2, 2, 4, 5] -> 8 / sqrt(10 * 8) (scipy.stats.spearmanr: 0.8944).
        self.assertAlmostEqual(spearman_ties([1, 2, 3, 4, 5], [0, 0, 0, 1, 2]), 0.894427191, places=8)


class TestObservationalScoring(unittest.TestCase):
    """code/observational/UPSTREAM-README.md's table, for the 2026-08-20 run."""

    EXPECTED = {  # label: (coherence, direction k/n, control shift, pass, rho)
        "Haiku 4.5": (0.009, (13, 13), 0.100, False, 0.70),
        "Sonnet 5": (0.003, (13, 13), 0.020, True, 0.81),
        "Opus 5": (0.001, (13, 13), 0.028, True, 0.87),
        "Fable 5": (0.001, (13, 13), 0.014, True, 0.88),
    }

    def test_metrics_match_score_bench(self):
        b = observational.build(run_path=OBS_RUN_2026_08_20)
        self.assertEqual(b["run"]["responses"], 540)
        self.assertEqual(b["pairs"], {"scored": 21, "positive": 13, "control": 8, "probe": 6, "total": 27})
        got = {m["label"]: m for m in b["models"]}
        self.assertEqual(set(got), set(self.EXPECTED))
        for label, (coh, (k, n), ctrl, ok, rho) in self.EXPECTED.items():
            m = got[label]
            self.assertEqual(f"{m['coherence']:.3f}", f"{coh:.3f}", label)
            self.assertEqual((m["direction"]["k"], m["direction"]["n"]), (k, n), label)
            self.assertEqual(f"{m['controlShift']:.3f}", f"{ctrl:.3f}", label)
            self.assertEqual(m["pass"], ok, label)
            self.assertEqual(round(m["rho"], 2), rho, label)
            self.assertEqual(m["pairsScored"], 21, label)
        self.assertEqual(b["nPass"], 3)
        self.assertEqual(b["best"]["label"], "Fable 5")
        self.assertEqual(b["noise"]["ceiling"], 0.939)

    def test_gradient_over_the_four(self):
        b = observational.build(run_path=OBS_RUN_2026_08_20)
        self.assertEqual(b["rho"], 1.0)   # four models, monotone in ECI


if __name__ == "__main__":
    unittest.main()
