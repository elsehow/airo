"""redlines/tools.py and the FRI Forecaster's copy (fri_forecaster/tools.py)
must stay the same search stack: AIRO's own loop and the pi harness are
compared as loops, never as two search implementations.

The copy exists because AIRO's core must not depend on the package while
it is private (main is published to a public repo); when it is public,
redlines/tools.py becomes a re-export and this test goes. Skipped where the
package is not installed."""
import inspect
import unittest

from redlines import tools as airo_tools

try:
    from fri_forecaster import tools as ff_tools
except ImportError:
    ff_tools = None


@unittest.skipIf(ff_tools is None, "fri_forecaster not installed")
class ToolsParity(unittest.TestCase):
    def test_same_functions(self):
        # The URL guard (2026-10-16, agent-box's `url-guard`) is part of the stack.
        for name in ("search_body", "web_search", "read_page", "blocked_patterns", "is_blocked"):
            self.assertEqual(inspect.getsource(getattr(airo_tools, name)),
                             inspect.getsource(getattr(ff_tools, name)), name)

    def test_same_tool_specs(self):
        strip = lambda ts: [{k: v for k, v in t.items() if k != "fn"} for t in ts]
        self.assertEqual(strip(airo_tools.FORECAST_TOOLS), strip(ff_tools.FORECAST_TOOLS))

    def test_same_constants(self):
        for name in dir(airo_tools):
            if name.isupper() and not name.endswith("_TOOL") and name != "FORECAST_TOOLS":  # tool dicts hold fn; compared above
                self.assertEqual(getattr(airo_tools, name), getattr(ff_tools, name, object()), name)
