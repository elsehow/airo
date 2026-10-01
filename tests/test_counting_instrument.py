"""Protect scientific scope, forecast windows and provenance across the cutover."""
import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from redlines.instrument import CURRENT_INSTRUMENT, counting_windows
from redlines.questions import load_ladder

ROOT = Path(__file__).resolve().parent.parent


class TestCountingInstrument(unittest.TestCase):
    def test_scientific_change_is_limited_to_dates_and_cyber_boundaries(self):
        old = json.loads((ROOT / 'data/instruments/legacy-2026-08-31/autoarc_ladder.json').read_text())
        new = load_ladder()
        # 2026-09-16: the extinction rung is an addendum's, beside the archived eight.
        self.assertEqual(old['rungs'], [r for r in new['rungs'] if not r.get('since')])
        # 2026-09-15: the extinction addendum ADDS one subset relation; every
        # relation of the archived instrument is still present and unchanged.
        self.assertEqual(old['relations']['cross'], new['relations']['cross'])
        self.assertEqual(old['relations']['bracket'], new['relations']['bracket'])
        for rel in old['relations']['subset']:
            self.assertIn(rel, new['relations']['subset'])
        # The extinction rung's four questions (an addendum, 2026-09-16) are new;
        # every archived question is still there, in order, unchanged.
        current = [q for q in new['questions'] if not q.get('since')]
        self.assertEqual(len(current), len(old['questions']))
        for before, after in zip(old['questions'], current):
            self.assertEqual(before['id'], after['id'])
            self.assertEqual(before['text'], after['text'])
            self.assertEqual(before['details']['severity'], after['details']['severity'])
            self.assertEqual(before['details']['perfect_knowledge'], after['details']['perfect_knowledge'])
            if after['cause'] != 'cyber':
                self.assertEqual(before['criteria'], after['criteria'])
        old_cross = json.loads((ROOT / 'data/instruments/legacy-2026-08-31/autoarc_crosscutting.json').read_text())
        new_cross = json.loads((ROOT / 'data/autoarc_crosscutting.json').read_text())
        # The workbook's three questions are unchanged; the only additions are
        # the addendum's extinction pair, each stamped with its `since`.
        new_by_id = {q['id']: q for q in new_cross['questions']}
        for q in old_cross['questions']:
            self.assertEqual(q, new_by_id[q['id']])
        added = [q for q in new_cross['questions'] if q['id'] not in {o['id'] for o in old_cross['questions']}]
        self.assertEqual([q['id'] for q in added], ['extinction:general', 'extinction:ai'])
        self.assertTrue(all(q.get('since') == '2026-09-15' for q in added))

    def test_windows_advance_for_every_incident_horizon_and_handle_short_months(self):
        spec = load_ladder()
        q = spec['questions'][0]
        first = counting_windows(q, ['6mo', '12mo', '2030'], date(2026, 8, 31), spec)
        second = counting_windows(q, ['6mo', '12mo', '2030'], date(2027, 1, 10), spec)
        self.assertEqual(first['6mo']['end'], '2027-02-28')
        self.assertEqual(first['12mo']['end'], '2027-08-31')
        self.assertEqual(first['2030']['end'], second['2030']['end'])
        self.assertEqual(first['2030']['start'], '2026-08-31')
        self.assertEqual(second['2030']['start'], '2027-01-10')
        self.assertEqual(first['2030']['harm_years'], 3)
        self.assertIsNone(counting_windows({'category': 'crosscutting'}, ['2030'], date(2026, 9, 10), spec))

    def test_joint_rows_retain_the_batch_date_and_exact_prompt(self):
        module_spec = importlib.util.spec_from_file_location('counting_runner', ROOT / 'code/run_unified.py')
        runner = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(runner)
        groups, by_group, horizons, _, spec = runner.load_batch(runner.LADDER, runner.CROSS, runner.UNBATCHED)
        policies = runner.load_policies(runner.COMBINED)
        conds = runner.expand_conditions(['all'], policies)
        keys = [runner.UNCONDITIONAL_KEY] + [c['id'] for c in conds]
        answer = {'rationale': 'fixture', 'eci_forecast': {'p10': 170, 'p25': 172, 'p50': 175, 'p75': 180, 'p90': 190},
                  'forecasts': [{'question_id': q['id'], 'horizon': h, 'probabilities': {k: .1 for k in keys}}
                                for qs in by_group.values() for q in qs for h in horizons if h in q['horizons']]}
        with patch.object(runner, 'call_tools', return_value=(answer, [])) as call:
            rows = runner.run_one_joint('fixture', 'fixture', groups, by_group, horizons,
                                       'after-midnight', 0, spec, conds, policies,
                                       today=date(2026, 9, 10))
        prompt = call.call_args.args[1]
        self.assertIn('2030: 2026-09-10 through 2030-12-31', prompt)
        self.assertEqual({r['run_date'] for r in rows}, {'2026-09-10'})
        self.assertEqual({r['instrument_version'] for r in rows}, {CURRENT_INSTRUMENT})
        self.assertEqual({r['prompt_sha256'] for r in rows}, {hashlib.sha256(prompt.encode()).hexdigest()})
        self.assertEqual([r['prompt'] for r in rows if r['prompt']], [prompt])
        self.assertEqual([r['system_prompt'] for r in rows if r['system_prompt']], [runner.SYSTEM])
        self.assertTrue(all(':combined:' in r['call_id'] for r in rows))
        for row in rows:
            if row['question_id'].startswith('ladder:'):
                self.assertEqual(row['counting_window']['2030']['start'], '2026-09-10')
            else:
                self.assertIsNone(row['counting_window'])


if __name__ == '__main__':
    unittest.main()
