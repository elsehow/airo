"""publish_dashboard.sh must rebuild every page blob the run log feeds.

The 2026-09-17 lesson: the rationales blob was built by `assemble` only, so
the box's cron publish (validator, then `build --views ...`) would have left
the "Why these forecasts?" panels pointing at a stale elicitation after the
next run. Every view in VIEW_ORDER is run-log-driven except the frozen
artifacts whose inputs live on the laptop; those pass through untouched.
"""
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from redlines.__main__ import BUILDERS, VIEW_ORDER  # noqa: E402

FROZEN = {"g3", "g4", "observational", "causal"}


class TestPublishViews(unittest.TestCase):
    def test_publish_rebuilds_every_run_log_view(self):
        script = (REPO_ROOT / "code" / "publish_dashboard.sh").read_text()
        m = re.search(r"python3 -m redlines build --views (\S+)", script)
        self.assertIsNotNone(m, "publish_dashboard.sh no longer calls `redlines build --views`")
        views = m.group(1).split(",")
        self.assertTrue(set(views) <= set(BUILDERS), f"unknown view(s): {set(views) - set(BUILDERS)}")
        self.assertEqual(set(views), set(VIEW_ORDER) - FROZEN)


if __name__ == "__main__":
    unittest.main()
