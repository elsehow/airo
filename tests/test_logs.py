"""redlines.logs: a log name resolves to its per-run files."""
import json
import tempfile
import unittest
from pathlib import Path

from redlines import logs


class TestLogs(unittest.TestCase):
    def test_folder_file_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            name = Path(d) / "conditional_runs_x.jsonl"
            self.assertFalse(logs.log_exists(name))
            for run, n in (("2026-09-18T1200Z", 2), ("2026-09-16T1645Z", 1)):
                logs.run_file(name, run).write_text("".join(json.dumps({"run_id": run, "i": i}) + "\n" for i in range(n)))
            self.assertEqual([r["run_id"] for r in logs.iter_rows(name)],
                             ["2026-09-16T1645Z", "2026-09-18T1200Z", "2026-09-18T1200Z"])
            self.assertEqual(logs.log_names(d), [name])
            plain = Path(d) / "experiment.jsonl"
            plain.write_text('{"a": 1}\n\n')
            self.assertEqual(list(logs.iter_rows(plain)), [{"a": 1}])
