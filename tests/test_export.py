"""The downloads: results/forecasts.csv, results/rationales.csv and the
bundle results/redlines-data.zip.

The CSVs are built from the same rows (redlines.export._published_rows:
EVERY run-log row, stamped or not, plus every instrument log's conditional
rows), so every forecast line has a rationale line to join to on call_id +
question_id + condition, and every model that ever ran is in both (project
lead, 2026-09-08: include everything, even if it requires a .zip). The
panel_set column carries the dashboard's own filter.

Run with:  python3 -m unittest tests.test_export -v
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from redlines import export  # noqa: E402
from redlines.runlog import load_runlog  # noqa: E402


class TestDownloads(unittest.TestCase):
    def test_every_forecast_has_a_rationale_line_and_every_panel_model_is_in_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            f_out, r_out = Path(tmp) / "f.csv", Path(tmp) / "r.csv"
            n = export.forecasts_csv(out=f_out)
            m = export.rationales_csv(out=r_out)
            f = list(csv.DictReader(open(f_out)))
            r = list(csv.DictReader(open(r_out)))
        self.assertEqual(len(f), n)
        self.assertEqual(len(r), m)
        self.assertEqual(list(r[0]), export.RATIONALE_COLUMNS)
        key = lambda d: (d["call_id"], d["question_id"], d["condition"])  # noqa: E731
        rkeys = {key(d) for d in r}
        self.assertEqual(len(rkeys), len(r), "one rationale line per call x question x condition")
        missing = {key(d) for d in f} - rkeys
        self.assertEqual(missing, set(), f"{len(missing)} forecast keys without a rationale line")
        # Every model with a run-log row -- the current panel, the departed,
        # and the pre-panel frontier five (panel_set empty on their rows).
        labels = {row["label"] for row in load_runlog(panel_only=False)}
        self.assertEqual({d["model"] for d in f} & labels, labels)
        self.assertEqual({d["model"] for d in r} & labels, labels)
        self.assertIn("Gemini 3.1 Pro", labels)
        self.assertTrue(any(d["model"] == "Gemini 3.1 Pro" and d["panel_set"] == "" for d in f))
        self.assertTrue(any(d["panel_set"] == "eci_topk" and d["panel_snapshot"] for d in f))
        # The rationale is the text the model wrote; the grounded runs have one.
        with_text = sum(1 for d in r if d["rationale"].strip())
        self.assertGreater(with_text, 0.9 * len(r))

    def test_bundle_carries_the_csvs_the_raw_logs_the_questions_and_a_readme(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            f_out, r_out, z_out = (Path(tmp) / n for n in ("f.csv", "r.csv", "b.zip"))
            export.forecasts_csv(out=f_out)
            export.rationales_csv(out=r_out)
            k = export.bundle_zip(out=z_out, forecasts=f_out, rationales=r_out)
            with zipfile.ZipFile(z_out) as z:
                names = z.namelist()
                readme = z.read("README.md").decode()
        self.assertEqual(len(names), k)
        for must in ("README.md", "forecasts.csv", "rationales.csv",
                     "raw/forecast_runs_unified.jsonl",
                     "raw/legacy-forecasts/forecast_runs.jsonl", "questions/autoarc_ladder.json",
                     "conditions/combined_conditions.json"):
            self.assertIn(must, names)
        self.assertTrue(any(n.startswith("raw/runs/") and n.endswith(".jsonl") for n in names))
        self.assertTrue(any(n.startswith("raw/conditional_runs_combined/") and n.endswith(".jsonl") for n in names))
        self.assertTrue(any(n.startswith("conditions/epoch_capabilities_index_") for n in names))
        for col in export.COLUMNS + export.RATIONALE_COLUMNS:
            self.assertIn(col, readme)


if __name__ == "__main__":
    unittest.main()
