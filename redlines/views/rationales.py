"""Original explanations attached to the calls used by current charts."""
from collections import defaultdict

from ..runlog import (load_runlog, complete_panel_rows, latest_instrument_rows,
                      current_rows, elicitation_date)


def build():
    all_rows = load_runlog()
    rows = current_rows(complete_panel_rows(latest_instrument_rows(all_rows)))
    debriefs = {r['call_id']: r['debrief'] for r in all_rows if r.get('debrief')}
    calls, questions = {}, defaultdict(lambda: defaultdict(list))
    for r in rows:
        cid = r.get('call_id') or f"{r['run_id']}:{r['label']}"
        calls[cid] = {
            'model': r['label'], 'modelId': r['model'], 'run': r['run_id'],
            'elicitedAt': r['elicited_at'], 'date': elicitation_date(r),
            'instrument': r.get('instrument_version'), 'protocol': r.get('protocol'),
            'rationale': r.get('rationale') or '', 'sources': r.get('key_sources') or [],
            'debriefs': debriefs.get(cid, {}),
        }
        questions[r['question_id']][r['label']].append(cid)
    return {'calls': calls, 'questions': dict(questions)}
