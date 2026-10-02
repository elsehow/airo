#!/usr/bin/env python3
"""Audit a complete, dated launch snapshot without changing it.

By default the combined instrument alone (the headline series and the policy
and capability panels), which is what the scheduled run elicits since the
axes instruments left the schedule on 2026-09-14. --sets audits others, e.g.
--sets combined,axes,paperaxes for a date on which all three were run.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redlines.instrument import CURRENT_INSTRUMENT, counting_windows
from redlines.logs import iter_rows, log_files
from redlines.registry import published_panel
from redlines.superseded import is_superseded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT / 'results')
    parser.add_argument('--date', type=date.fromisoformat, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sets', default='combined',
                        help='comma-separated instrument slugs to audit (default: combined)')
    args = parser.parse_args()
    files = {'combined': 'combined_conditions.json', 'axes': 'axes_conditions.json',
             'paperaxes': 'paper_axes_conditions.json'}
    sets = [s.strip() for s in args.sets.split(',') if s.strip()]
    unknown = [s for s in sets if s not in files]
    if unknown:
        parser.error(f"unknown instrument set(s) {unknown}; choose from {sorted(files)}")
    module = importlib.util.spec_from_file_location('launch_runner', ROOT / 'code/run_unified.py')
    ru = importlib.util.module_from_spec(module)
    module.loader.exec_module(ru)
    labels = {m['label'] for m, _ in published_panel()}
    report = {'date': args.date.isoformat(), 'instrument_version': CURRENT_INSTRUMENT,
              'models': sorted(labels), 'instruments': {}, 'errors': [], 'coherence_warnings': [],
              # The debrief (2026-09-15) is asked after the forecasts are accepted
              # and cannot move them, so a missing or incomplete one is a warning
              # for the brief's author, never a reason to withhold the page.
              'debrief_warnings': []}

    def check(ok, kind, detail):
        if not ok:
            report['errors'].append({'check': kind, 'detail': detail})

    for slug in sets:
        filename = files[slug]
        path = args.results / f'conditional_runs_{slug}.jsonl'
        raw = b''.join(f.read_bytes() for f in log_files(path))
        # A draw the same day replaced (redlines.superseded) is not part of
        # the day's grid: without this, a re-run day fails as duplicates.
        rows = [r for r in iter_rows(path) if r.get('run_date') == args.date.isoformat()
                and r.get('instrument_version') == CURRENT_INSTRUMENT
                and not is_superseded(r)]
        policies = ru.load_policies(ROOT / 'data' / filename)
        policies = ru.resolve_set(policies, args.date)
        conds = ru.expand_conditions(['all'], policies)
        groups, by_group, horizons, _, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
        horizons = ru.set_horizons(policies, horizons)
        qs = {q['id']: q for g in groups for q in by_group[g['key']]}
        prompt, n, cells = ru.build_prompt_joint(groups, by_group, horizons, spec, conds, policies, args.date)
        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
        conditions = {None} | {c['id'] for c in conds}
        expected = {(label, q, c) for label in labels for q in qs for c in conditions}
        keys = Counter((r['label'], r['question_id'], (r.get('condition') or {}).get('id')) for r in rows)
        check(set(keys) == expected and all(v == 1 for v in keys.values()), 'complete_unique_grid',
              {'set': slug, 'expected_rows': len(expected), 'actual_rows': len(rows),
               'missing': len(expected-set(keys)), 'extra': len(set(keys)-expected),
               'duplicates': sum(v-1 for v in keys.values())})
        calls, probabilities = defaultdict(list), {}
        for r in rows:
            q = qs.get(r['question_id'])
            if q is None:
                continue
            ident = [slug, r['label'], r['question_id'], (r.get('condition') or {}).get('id')]
            hs = {h for h in horizons if h in q['horizons']}
            fs = r.get('forecasts') or []
            check(len(fs) == len(hs) and {f['horizon'] for f in fs} == hs,
                  'complete_horizons', ident)
            check(r.get('protocol') == policies['protocol'], 'protocol', ident)
            check(r.get('prompt_sha256') == prompt_sha, 'prompt_hash', ident)
            check(r.get('counting_window') == counting_windows(q, horizons, args.date, spec),
                  'incident_window', ident)
            check(r.get('resolves_on') == {h: ru.resolves_on(h, args.date, spec) for h in horizons},
                  'resolution_dates', ident)
            for f in fs:
                p = f.get('probability')
                valid = isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) and 0 <= p <= 1
                check(valid, 'bounded_probability', ident+[f.get('horizon'), p])
                if valid:
                    probabilities[tuple(ident[1:])+ (f['horizon'],)] = p
            calls[r['call_id']].append(r)
        call_report = []
        for call_id, rs in calls.items():
            retained = [r for r in rs if r.get('prompt')]
            check(len(retained) == 1, 'one_retained_prompt', call_id)
            if retained:
                first = retained[0]
                check(first['prompt'] == prompt and first.get('system_prompt') == ru.SYSTEM,
                      'exact_prompt_replay', call_id)
                evidence = [e for r in rs for e in r.get('evidence') or []]
                check(len(evidence) >= ru.MIN_RESEARCH and all(r.get('grounded') for r in rs),
                      'grounding_floor', call_id)
                check(bool(first.get('rationale')), 'rationale_present', call_id)
                status = first.get('debrief_status') or {}
                if not (isinstance(first.get('debrief'), dict) and status.get('complete')):
                    report['debrief_warnings'].append({
                        'set': slug, 'call_id': call_id, 'label': first['label'],
                        'attempts': status.get('attempts'), 'error': status.get('error'),
                        'problems': status.get('problems') or (['no debrief recorded'] if not status else [])})
                for elicit in ru.set_elicits(policies):
                    value = (first.get('elicited') or {}).get(elicit['key'])
                    check(bool(ru.clean_elicit(value, elicit)), 'elicited_metadata', [call_id, elicit['key']])
                call_report.append({'call_id': call_id, 'label': first['label'], 'rows': len(rs),
                                    'evidence': len(evidence), 'usage': first.get('usage'),
                                    'submission': first.get('delivery')})
        rungs = [r['short'] for r in spec['rungs']]

        def ordered(left, right, kind):
            a, b = probabilities.get(left), probabilities.get(right)
            if a is not None and b is not None and a > b + 1e-9:
                report['coherence_warnings'].append({'set': slug, 'check': kind,
                    'left': left, 'right': right, 'values': [a, b], 'excess_pp': (a-b)*100})

        for label in labels:
            for c in conditions:
                for q in qs:
                    hs = sorted([h for h in horizons if h in qs[q]['horizons']],
                                key=lambda h: ru.resolves_on(h, args.date, spec))
                    for h1, h2 in zip(hs, hs[1:]):
                        ordered((label,q,c,h1), (label,q,c,h2), 'horizon')
                for h in horizons:
                    ordered((label,'catastrophe:ai',c,h), (label,'catastrophe:general',c,h), 'ai_within_general')
                    for cause in ('ai','cyber','bio','misalign'):
                        for lo, hi in zip(rungs, rungs[1:]):
                            ordered((label,f'ladder:{cause}:{hi}',c,h),
                                    (label,f'ladder:{cause}:{lo}',c,h), 'severity')
                        if cause != 'ai':
                            for rung in rungs:
                                ordered((label,f'ladder:{cause}:{rung}',c,h),
                                        (label,f'ladder:ai:{rung}',c,h), 'subtype_within_ai')
        report['instruments'][slug] = {'file_sha256': hashlib.sha256(raw).hexdigest(),
            'prompt_sha256': prompt_sha, 'rows': len(rows), 'probabilities': len(probabilities),
            'expected_probabilities': cells * len(conditions) * len(labels), 'calls': call_report}
    report['passed_integrity_checks'] = not report['errors']
    report['recorded_cost_usd'] = round(sum((c.get('usage') or {}).get('cost_usd',0)
        for s in report['instruments'].values() for c in s['calls']),6)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'integrity_errors': len(report['errors']),
                      'coherence_warnings': len(report['coherence_warnings']),
                      'debrief_warnings': len(report['debrief_warnings']),
                      'recorded_cost_usd': report['recorded_cost_usd'], 'report': str(args.out)}))
    return int(bool(report['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
