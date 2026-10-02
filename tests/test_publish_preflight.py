"""Publication must reject incomplete inputs before build or served-file writes."""
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestPublishPreflight(unittest.TestCase):
    def fixture(self, directory, status=1):
        root = Path(directory)
        for name in ('redlines', 'code', 'results', 'served', 'web/fonts', 'web/img'):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / 'redlines/__init__.py').write_text('')
        (root / 'redlines/instrument.py').write_text("CURRENT_INSTRUMENT = 'current-test'\n")
        (root / 'redlines/runlog.py').write_text('def load_runlog(panel_only=False): return []\n')
        (root / 'redlines/logs.py').write_text((ROOT / 'redlines/logs.py').read_text())
        (root / 'redlines/__main__.py').write_text("from pathlib import Path\nPath('build-called').write_text('yes')\n")
        (root / 'code/validate_launch_run.py').write_text('''import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--date');p.add_argument('--out');a=p.parse_args()
Path('validator-date').write_text(a.date)
out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
status=int(Path('validator-status').read_text())
out.write_text(json.dumps({'passed_integrity_checks':not status,'coherence_warnings':['audit only']}))
raise SystemExit(status)
''')
        (root / 'validator-status').write_text(str(status))
        for slug in ('combined', 'axes', 'paperaxes'):
            (root / f'results/conditional_runs_{slug}.jsonl').write_text(json.dumps({
                'instrument_version': 'current-test', 'run_date': '2026-09-10'}) + '\n')
        (root / 'served/index.html').write_text('last successful publication')
        (root / 'index.html').write_text('new publication')
        for name in ('forecasts.csv', 'rationales.csv', 'redlines-data.zip'):
            (root / 'results' / name).write_text('fixture')
        script = (ROOT / 'code/publish_dashboard.sh').read_text()
        patched = script.replace(
            'REPO="${REDLINES_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"',
            'REPO=' + shlex.quote(str(root)))
        patched = patched.replace('DOCROOT="${REDLINES_DOCROOT:-/var/www/html}"',
                                  'DOCROOT=' + shlex.quote(str(root / 'served')))
        # Both substitutions must land, or the test would run the real script
        # against the real repo and docroot.
        assert patched.count(shlex.quote(str(root))) >= 2, "publish_dashboard.sh REPO/DOCROOT lines changed; update this patch"
        script = patched
        (root / 'publish.sh').write_text(script)
        return root

    def run_script(self, root):
        return subprocess.run(['bash', str(root / 'publish.sh')], text=True, capture_output=True)

    def assert_preserved(self, root, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((root / 'build-called').exists())
        self.assertEqual(list((root / 'served').iterdir()), [root / 'served/index.html'])
        self.assertEqual((root / 'served/index.html').read_text(), 'last successful publication')

    def test_newest_partial_instrument_blocks_build_and_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            with (root / 'results/conditional_runs_combined.jsonl').open('a') as f:
                f.write(json.dumps({'instrument_version':'current-test','run_date':'2026-09-11'})+'\n')
                # A later obsolete run cannot set the validation date.
                f.write(json.dumps({'instrument_version':'legacy','run_date':'2026-09-12'})+'\n')
            with (root / 'results/conditional_runs_axes.jsonl').open('a') as f:
                # Nor can a later axes date: the axes instruments left the
                # schedule on 2026-09-14 and no longer gate publication.
                f.write(json.dumps({'instrument_version':'current-test','run_date':'2026-09-13'})+'\n')
            self.assert_preserved(root, self.run_script(root))
            self.assertEqual((root / 'validator-date').read_text(), '2026-09-11')
            self.assertTrue((root / 'results/validation/latest-integrity.json').exists())

    def test_missing_instrument_or_current_date_preserves_site(self):
        for missing_file in (True, False):
            with self.subTest(missing_file=missing_file), tempfile.TemporaryDirectory() as d:
                root = self.fixture(d)
                if missing_file:
                    (root / 'results/conditional_runs_combined.jsonl').unlink()
                else:
                    for path in (root / 'results').glob('*.jsonl'): path.write_text('')
                self.assert_preserved(root, self.run_script(root))
                self.assertFalse((root / 'validator-date').exists())
                report = json.loads((root / 'results/validation/latest-integrity.json').read_text())
                self.assertFalse(report['passed_integrity_checks'])

    def test_integrity_success_with_coherence_warnings_allows_fixture_publish(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d, status=0)
            result = self.run_script(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / 'build-called').exists())
            self.assertEqual((root / 'served/index.html').read_text(), 'new publication')
            self.assertEqual((root / 'served/redlines-data.zip').read_text(), 'fixture')
