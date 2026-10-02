"""Current forecasts share the headline panel before any aggregation."""
import copy
import unittest
from unittest.mock import patch

from redlines.views import axes, capability, conditional
from redlines.instrument import CURRENT_INSTRUMENT
from tests.test_instrument_views import current


def _current_fixture():
    from redlines.logs import iter_rows
    rows = list(iter_rows(capability.REPO_ROOT / 'results/conditional_runs_combined.jsonl'))
    return current([r for r in rows if r['elicited_at'][:10] == '2026-09-08'
                    and r.get('protocol') == 'unified-joint-combined-v4'])


class TestCurrentForecastPanel(unittest.TestCase):
    @staticmethod
    def _with_retired(rows):
        extra = copy.deepcopy([r for r in rows if r['label'] == rows[0]['label']])
        for r in extra:
            r['label'] = 'Fable 5'
            r['model'] = 'anthropic/claude-fable-5'
            r['call_id'] = 'retired:' + r.get('call_id', '')
            for f in r.get('forecasts', []):
                f['probability'] = 0.99
            e = (r.get('elicited') or {}).get('eci_forecast') or {}
            for field in e:
                if field.startswith('p'):
                    e[field] += 1000
        return rows + extra

    def test_capability_filters_before_risk_and_eci_aggregation(self):
        with patch.object(capability, 'load_conditional', return_value=_current_fixture()):
            expected = capability.build()
            spec, rows, *rest = capability._pick(capability.VARIANTS[0][1])
        self.assertNotIn('Fable 5', {r['label'] for r in rows})
        poisoned = self._with_retired(rows)
        with patch.object(capability, '_pick', return_value=(spec, poisoned, *rest)):
            self.assertEqual(capability.build(), expected)
            # An explicitly supplied historical variant keeps its actual panel.
            historical = capability.build(variants=list(capability.VARIANTS))
        self.assertNotEqual(historical['variants'][0]['forecast']['ensemble'],
                            expected['variants'][0]['forecast']['ensemble'])
        self.assertIn('Fable 5', {m['label'] for m in historical['variants'][0]['models']})

    def test_policy_filters_before_ensemble_aggregation(self):
        with patch.object(conditional, 'load_conditional', return_value=_current_fixture()):
            expected = conditional.build()
            source = conditional.pick_source(conditional.SOURCES, None)
        source = copy.deepcopy(source)
        source['rows'] = self._with_retired(source['rows'])
        with patch.object(conditional, 'pick_source', return_value=source):
            self.assertEqual(conditional.build(), expected)

    def test_axes_default_filters_but_explicit_history_keeps_roster(self):
        from tests.test_axes_view import _rows
        rows = _rows()
        with patch.object(axes, '_rows', return_value=(rows, 'test', '2026-09-04')):
            default = axes.build()
            historical = axes.build(log_path=axes.LOG)
        self.assertEqual(default['models'], [])
        self.assertFalse(default['instrumentInfo']['available'])
        self.assertEqual({m['label'] for m in historical['models']}, {'Fable 5', 'GPT-5.5 Pro'})

    def test_no_canonical_run_cannot_publish_one_unstamped_model(self):
        rows = [{'label': 'current model', 'instrument_version': CURRENT_INSTRUMENT}]
        with patch.object(conditional, 'load_runlog', return_value=[]):
            self.assertEqual(conditional.current_forecast_rows(rows), [])
