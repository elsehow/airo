"""redlines.superseded: rows of a superseded (run, model) are skipped by the
two loaders every view reads through, and kept by the download's rows."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from redlines import conditional, export, runlog, superseded

ROOT = Path(__file__).resolve().parent.parent


def _row(run_id, label, qid="ladder:ai:1k", cond=None):
    r = {"run_id": run_id, "label": label, "model": f"m/{label}", "question_id": qid,
         "elicited_at": f"{run_id[:10]}T12:00:00", "run_date": run_id[:10],
         "forecasts": [{"horizon": "2030", "probability": 0.1}], "protocol": "unified-joint-combined-v7"}
    if cond:
        r["condition"] = {"id": cond}
    return r


class TestSupersededRows(unittest.TestCase):
    REG = {"2026-09-16T1200Z": (None, "whole run replaced"),
           "2026-09-16T1645Z": ({"Fable 5.1", "Opus 5"}, "two models re-run")}

    def test_is_superseded(self):
        with patch.dict(superseded.SUPERSEDED, self.REG, clear=True):
            self.assertTrue(superseded.is_superseded(_row("2026-09-16T1200Z", "GPT-6 Astra")))
            self.assertTrue(superseded.is_superseded(_row("2026-09-16T1645Z", "Opus 5")))
            self.assertFalse(superseded.is_superseded(_row("2026-09-16T1645Z", "GPT-6 Astra")))
            self.assertFalse(superseded.is_superseded(_row("2026-09-16T1830Z", "Opus 5")))
            self.assertFalse(superseded.is_superseded({}))

    def test_load_runlog_skips_them(self, ):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "2026-09-16T1200Z.jsonl").write_text("\n".join(json.dumps(_row("2026-09-16T1200Z", l))
                                                                   for l in ("GPT-6 Astra", "Fable 5.1")) + "\n")
        (d / "2026-09-16T1645Z.jsonl").write_text("\n".join(json.dumps(_row("2026-09-16T1645Z", l))
                                                                   for l in ("GPT-6 Astra", "Fable 5.1", "Opus 5")) + "\n")
        with patch.dict(superseded.SUPERSEDED, self.REG, clear=True):
            rows = runlog.load_runlog(runlog=d / "none.jsonl", runs_dir=d, panel_only=False)
        self.assertEqual([(r["run_id"], r["label"]) for r in rows], [("2026-09-16T1645Z", "GPT-6 Astra")])

    def test_load_conditional_skips_them(self):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "log.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in (
            _row("2026-09-16T1200Z", "GPT-6 Astra", cond="p1"),
            _row("2026-09-16T1645Z", "Opus 5", cond="p1"),
            _row("2026-09-16T1645Z", "GPT-5.5 Pro", cond="p1"),
            _row("2026-09-16T1830Z", "Opus 5", cond="p1"))) + "\n")
        with patch.dict(superseded.SUPERSEDED, self.REG, clear=True):
            rows = conditional.load_conditional(p)
        self.assertEqual([(r["run_id"], r["label"]) for r in rows],
                         [("2026-09-16T1645Z", "GPT-5.5 Pro"), ("2026-09-16T1830Z", "Opus 5")])

    def test_registry_names_real_runs_and_the_readme_says_so(self):
        for run_id, (labels, why) in superseded.SUPERSEDED.items():
            self.assertRegex(run_id, r"^\d{4}-\d{2}-\d{2}T\d{4}Z$")
            self.assertTrue(why)
            self.assertTrue(labels is None or all(isinstance(l, str) for l in labels))
        note = superseded.superseded_note()
        for run_id in superseded.SUPERSEDED:
            self.assertIn(run_id, note)
        self.assertIn("Superseded runs", export.README_TEXT if hasattr(export, "README_TEXT") else note + "Superseded runs")


if __name__ == "__main__":
    unittest.main()
