#!/usr/bin/env python3
"""Regenerate the two launch-paper charts previously supplied as static PNGs.

Uses current dashboard ladder data and version-matched conditional raw rows.
Writes the plotted values alongside PNG/PDF outputs for numerical review.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from redlines.instrument import CURRENT_INSTRUMENT, instrument_rows
from redlines.logs import iter_rows  # noqa: E402
from redlines.runlog import current_panel, load_runlog
from redlines.paper.dates import month_year

COLORS = ['#0072B2', '#D55E00', '#009E73']
STYLES = ['-', '--', ':']
MARKERS = ['o', 's', '^']
HORIZONS = ['2030', '2050', '2100']


def load(name):
    return json.loads((ROOT / name).read_text())


def axis_data(slug, keys):
    spec = load('data/' + ('axes_conditions.json' if slug == 'axes' else 'paper_axes_conditions.json'))
    path = ROOT / f'results/conditional_runs_{slug}.jsonl'
    rows = instrument_rows(list(iter_rows(path)))
    rows = [r for r in rows if r['question_id'] == 'catastrophe:ai' and r.get('protocol') == spec['protocol']]
    day = max(r['run_date'] for r in rows)
    rows = [r for r in rows if r['run_date'] == day]
    labels = current_panel(instrument_rows(load_runlog()))
    if len(labels) != 4:
        raise ValueError('The launch figures require the complete four-model canonical panel.')
    latest = {}
    for r in sorted(rows, key=lambda r: r['elicited_at']):
        if r['label'] in labels and r.get('condition'):
            latest[(r['label'], r['condition']['id'])] = r
    axes = []
    for key in keys:
        conditions = [c for c in spec['conditions'] if c['group'] == key]
        points = []
        for c in conditions:
            by_horizon = {}
            for h in HORIZONS:
                ps = {}
                for label in sorted(labels):
                    row = latest[(label, c['id'])]
                    ps[label] = next(f['probability'] * 100 for f in row['forecasts'] if f['horizon'] == h)
                by_horizon[h] = {'median': statistics.median(ps.values()), 'models': ps}
            points.append({'id': c['id'], 'x': c['value'], 'by_horizon': by_horizon})
        axes.append({'key': key, 'day': day, 'points': points})
    return axes


def save(fig, name, out, plt):
    fig.savefig(out / f'{name}.png', dpi=240, bbox_inches='tight')
    fig.savefig(out / f'{name}.pdf', bbox_inches='tight')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
                         'axes.spines.top':False, 'axes.spines.right':False,
                         'axes.edgecolor':'#aaaaaa', 'grid.color':'#dddddd',
                         'legend.frameon':False, 'pdf.fonttype':42})
    ladder = load('results/graph2_data.json')
    if ladder.get('instrumentInfo', {}).get('version') != CURRENT_INSTRUMENT:
        raise ValueError('Ladder data does not match the new instrument.')
    fig, axs = plt.subplots(1, 3, figsize=(12, 4), sharey=True)
    plotted_ladder = {}
    for ax, h in zip(axs, HORIZONS):
        curves = {c['key']:c for c in ladder['byHorizon'][h]['causes']}
        plotted_ladder[h] = {}
        for i, (key, label) in enumerate([('cyber','Cyber'),('misalign','Misalignment'),('bio','Biological')]):
            points = curves[key]['rungs']
            ys = [p['median'] for p in points]
            if any(y is None or y <= 0 for y in ys):
                raise ValueError('Log-scale chart needs an explicit treatment of zero/missing probabilities.')
            ax.plot(range(len(points)), ys, STYLES[i], color=COLORS[i], marker=MARKERS[i],
                    markersize=4, linewidth=1.8, label=label)
            plotted_ladder[h][key] = [{'rung':p['rung'],'probability_percent':p['median']} for p in points]
        rungs = load('data/autoarc_ladder.json')['rungs']
        def dollars(v):
            for unit, divisor in [('Q',1e15),('T',1e12),('B',1e9),('M',1e6)]:
                if v >= divisor:
                    return f'${v/divisor:g}{unit}'
        ax.set_xticks(range(len(rungs)), [f"{r['short']}\n{dollars(r['damages_usd'])}" for r in rungs], fontsize=8)
        ax.set_title(f'By {h}', weight='bold')
        ax.set_yscale('log')
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f'{v:g}%'))
        ax.grid(axis='y', which='major')
    axs[0].set_ylabel('Probability of reaching the threshold (log scale)')
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(.06,.89), ncol=3)
    fig.suptitle('AI incident risks across severity thresholds', x=.06, ha='left', weight='bold', fontsize=16)
    info = ladder['instrumentInfo']
    starts = sorted({w['start'] for ws in info.get('countingWindows',{}).values() for w in ws})
    fig.text(.06,.93, 'Unweighted median of four models | Onsets from ' + ', '.join(month_year(d) for d in starts), fontsize=10)
    fig.supxlabel('Severity: deaths or equivalent morbidity (top) OR economic damages (bottom)', fontsize=10)
    fig.subplots_adjust(top=.74, bottom=.2, wspace=.13)
    save(fig, 'incident_ladders', args.out, plt)

    axes = axis_data('axes', ['eci','agi','revenue']) + axis_data('paperaxes', ['gdp','lfpr','metr'])
    titles = ['A. Frontier capability','B. AGI timing','C. AI-company revenue',
              'D. Economic growth','E. Labor-force participation','F. Autonomous task performance']
    xlabels = ['Frontier ECI six months after elicitation','Year Expert AGI first occurs',
               'OpenAI + Anthropic annualized revenue\nat end of 2030 (billions of 2026 USD)',
               'Annual US real GDP growth, 2025–2030 (%)',
               'US labor-force participation\nin January 2030 (%)',
               'METR 80% task horizon\nat end of 2026 (hours)']
    fig, axs = plt.subplots(2, 3, figsize=(12, 8), sharey=True)
    max_risk = max(p['by_horizon'][h]['median']
                   for data in axes for p in data['points'] for h in HORIZONS)
    for ax, data, title, xlabel in zip(axs.flat, axes, titles, xlabels):
        xs = [p['x'] for p in data['points']]
        for i,h in enumerate(HORIZONS):
            ax.plot(xs, [p['by_horizon'][h]['median'] for p in data['points']], STYLES[i],
                    color=COLORS[i], marker=MARKERS[i], markersize=4, linewidth=1.8,label=f'By {h}')
        ax.set_xticks(xs)
        if data['key']=='agi':
            ax.tick_params(axis='x', labelrotation=30)
        ax.set_title(title, loc='left', weight='bold')
        ax.set_xlabel(xlabel)
        ax.set_ylim(0, max_risk * 1.08)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f'{v:g}%'))
        ax.grid(axis='y')
    handles,labels=axs[0,0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='upper left',bbox_to_anchor=(.06,.91),ncol=3)
    fig.suptitle('AI-catastrophe forecasts under six sets of conditions',x=.06,ha='left',weight='bold',fontsize=16)
    fig.text(.06,.93,'Unweighted median of four models | Elicited '+', '.join(sorted({month_year(a['day']) for a in axes})),fontsize=10)
    fig.supylabel('Forecast probability of AI catastrophe')
    fig.subplots_adjust(top=.8, bottom=.12, hspace=.65, wspace=.2, left=.08)
    save(fig,'conditional_appendix',args.out,plt)
    (args.out/'launch-figure-values.json').write_text(json.dumps({'instrument_version':CURRENT_INSTRUMENT,
        'incident_ladders':plotted_ladder,'conditional_axes':axes},indent=2)+'\n')
    print(f'Wrote both charts and their plotted values to {args.out}')


if __name__ == '__main__':
    main()
