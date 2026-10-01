"""Explanations and trails must refer to the forecasts actually displayed."""
import unittest

from redlines.runlog import (load_runlog, complete_panel_rows,
                            latest_instrument_rows, current_rows)
from redlines.views import graph2, rationales


class TestRationalesAndHistory(unittest.TestCase):
    def test_explanations_use_current_calls_and_question_debriefs(self):
        data = rationales.build()
        rows = current_rows(complete_panel_rows(latest_instrument_rows(load_runlog())))
        for r in rows:
            ids = data['questions'][r['question_id']][r['label']]
            self.assertIn(r['call_id'], ids)
            self.assertEqual(data['calls'][r['call_id']]['rationale'], r['rationale'])
        self.assertEqual(set(data['calls']), {r['call_id'] for r in rows})
        # Every call carries a debrief; a debrief can be partial (Fable 5.1
        # delivered 20 of 41 questions on 2026-09-18), so check what is there.
        for call in data['calls'].values():
            self.assertTrue(call['debriefs'])
            for d in call['debriefs'].values():
                self.assertTrue(d['rationale'])

    def test_history_does_not_change_latest_forecasts(self):
        with_history = graph2.build()
        without_history = graph2.build(include_history=False)
        history = with_history.pop('history')
        without_history.pop('history')
        self.assertEqual(with_history, without_history)
        dates = [s['date'] for s in history]
        self.assertTrue(dates)
        self.assertEqual(dates, sorted(dates))
        self.assertTrue(all(d < with_history['instrumentInfo']['runDate'] for d in dates))
        for snapshot in history:
            self.assertEqual(snapshot['instrumentInfo']['version'],
                             with_history['instrumentInfo']['version'])
            if snapshot['date'] >= '2026-09-16':    # the extinction rung's first run
                continue
            for horizon in snapshot['byHorizon'].values():
                for cause in horizon['causes']:
                    self.assertEqual(len(cause['rungs']), 8)
                    self.assertNotIn('extinction', [r['rung'] for r in cause['rungs']])

    def test_incomplete_prior_panel_is_not_a_trail(self):
        rows = [r for r in load_runlog()
                if not (r.get('run_date') == '2026-09-14' and r['label'] == 'GPT-6 Astra')]
        self.assertNotIn('2026-09-14', [s['date'] for s in graph2.build(rows)['history']])
