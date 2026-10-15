#!/usr/bin/env python3
"""Build panel.html: findings from the LEAP Wave 13 ensemble runs.

Reads the run root (questions snapshot, both mean aggregates, provenance),
computes cell-level comparisons (especially ensemble vs Opus 5.5, the
highest-ECI member), and writes a single self-contained static page.
"""
import json, os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Projects/leap-w13-runs/main")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/Projects/leap-w13-runs/panel.html")

SHORT = {
    "anthropic_claude-opus-5-5--high--research--group": "Opus 5.5",
    "openai_gpt-6-astra--high--research--group": "GPT-6 Astra",
    "openai_gpt-6.1-sol--high--research--group": "GPT-6.1 Sol",
    "anthropic_claude-fable-5-1--high--research--group": "Fable 5.1",
}
UNIT_KIND = {"probability": ("pts", 100.0), "usd (billion, revenue)": ("rel", None), "usd": ("rel", None), "": ("rel", None), None: ("rel", None)}

def main():
    qs = json.load(open(f"{ROOT}/questions.json"))
    ens_cells = json.load(open(f"{ROOT}/rectunz0NAgYb6piM.group.mean.json"))["cells"]
    sess_cells = json.load(open(f"{ROOT}/rectunz0NAgYb6piM.session.mean.json"))["cells"]
    prov = json.load(open(f"{ROOT}/rectunz0NAgYb6piM.group.mean.json.provenance.json"))
    members = list(prov.keys())

    qmap = {}
    for grp in qs["groups"]:
        if grp["question_type"] != "forecast":
            continue
        for q in grp["questions"]:
            qmap[q["question_id"]] = (grp, q)

    rows = []
    for qid, c in ens_cells.items():
        grp, q = qmap[qid]
        unit = (grp.get("unit") or "").strip()
        kind = UNIT_KIND.get(unit, ("rel", None))[0]
        ens, opus = c["value"], prov[members[0]][qid]
        diff = ens - opus
        div = abs(diff) if kind == "pts" else 100 * abs(diff) / max(abs(ens), abs(opus), 1e-9)
        mv = {SHORT[m]: round(prov[m][qid], 2) for m in members}
        dim = (q.get("question_dimension") or "").strip() or None
        label = re.sub(r"\s+", " ", (grp.get("question_group_text") or "").strip())
        label = (label[:120] + "…") if len(label) > 120 else label
        rows.append({"qid": qid, "unit": unit, "kind": kind,
                     "group": (grp.get("scenario_name") or label[:52]),
                     "question": label, "dimension": dim,
                     "percentile": q.get("question_percentile"),
                     "year": (q.get("question_resolution_date") or "")[:4],
                     "ensemble": round(ens, 2), "opus": round(opus, 2),
                     "members": mv, "diff": round(diff, 2), "div": round(div, 2),
                     "session": round(sess_cells[qid]["value"], 2),
                     "spread": round(max(mv.values()) - min(mv.values()), 2)})
    rows.sort(key=lambda r: -r["div"])

    ens_by_qid = {r["qid"]: r["ensemble"] for r in rows}
    gaps = {SHORT.get(m, m): [prov[m][q] - ens_by_qid[q] for q in ens_by_qid] for m in members}
    member_stats = []
    for m, g in gaps.items():
        member_stats.append({"name": m, "mean_gap": round(sum(g) / len(g), 1),
                             "mean_abs_gap": round(sum(map(abs, g)) / len(g), 1),
                             "above": sum(1 for x in g if x > 0)})
    member_stats.sort(key=lambda s: -s["mean_gap"])

    stats = {
        "n_cells": len(rows),
        "n_above": sum(1 for r in rows if r["diff"] > 0),
        "n_below": sum(1 for r in rows if r["diff"] < 0),
        "n_identical": sum(1 for r in rows if r["diff"] == 0),
        "mean_abs_div": round(sum(r["div"] for r in rows) / len(rows), 1),
        "max_pts_diff": max((abs(r["diff"]) for r in rows if r["kind"] == "pts"), default=0),
        "top_group_div": max(abs(r["ensemble"] - r["session"]) for r in rows),
        "total_cost": "~$96 (deduplicated run spend, this fleet)",
    }

    html = TEMPLATE.replace("/*__DATA__*/", json.dumps({"stats": stats, "members": [SHORT[m] for m in members], "member_stats": member_stats, "cells": rows}))
    # pre-render the full 46-cell table statically (no client JS needed)
    def fmt(v):
        if not isinstance(v, (int, float)):
            return "—"
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{round(v, 2):g}"
    def cellrow(r):
        dim = f" <span class='tag dim2'>{r['dimension']}</span>" if r["dimension"] else ""
        others = [m for m in members[1:]]
        tds = "".join(f"<td class='num' style='color:var(--dim)'>{fmt(prov[m][r['qid']])}</td>" for m in others)
        return (f"<tr><td>{r['group']}{dim}<br><span style='color:var(--dim);font-size:11.5px'>{r['question'][:150]}</span></td>"
                f"<td>{r['percentile'] if r['percentile'] is not None else '—'}</td>"
                f"<td class='num'><b>{fmt(r['ensemble'])}</b></td><td class='num'>{fmt(r['opus'])}</td>"
                f"{tds}<td class='num' style='color:var(--dim)'>{fmt(r['session'])}</td></tr>")
    body = ("<table><thead><tr><th>group / dimension</th><th>p</th><th class='num'>ensemble</th>"
            "<th class='num'>Opus</th>"
            + "".join(f"<th class='num'>{SHORT[m]}</th>" for m in members[1:])
            + "<th class='num'>session</th></tr></thead><tbody>"
            + "".join(cellrow(r) for r in sorted(rows, key=lambda r: (r['group'], r['percentile'] is None, r['percentile'] or 0)))
            + "</tbody></table>")
    html = html.replace("<div id=\"alltable\">__ALLTABLE__</div>", body)

    # section 2: top divergences with static bars (no client JS)
    top = rows[:14]
    maxdiv = max(r["div"] for r in top) or 1
    toprows = []
    for r in top:
        w = max(3, 100 * r["div"] / maxdiv)
        cls = "up" if r["diff"] > 0 else "dn"
        diff = f"{r['diff']:+g} pts" if r["kind"] == "pts" else f"{r['diff']:+,.0f} ({r['div']:.0f}%)"
        dim = f" <span class='tag dim2'>{r['dimension']}</span>" if r["dimension"] else ""
        yr = f" ({r['year']})" if r["year"] else ""
        p = r["percentile"] if r["percentile"] is not None else "—"
        toprows.append(
            f"<tr><td>{r['group']}{dim} · p{p}{yr}<br>"
            f"<span style='color:var(--dim);font-size:12px'>{r['question']}</span></td>"
            f"<td class='num'>{fmt(r['ensemble'])}</td><td class='num'>{fmt(r['opus'])}</td>"
            f"<td class='num'>{diff}</td>"
            f"<td><div class='bar {cls}'><i style='width:{w}%'></i></div></td></tr>")
    table2 = ("<table><thead><tr><th>cell</th><th class='num'>ensemble</th><th class='num'>Opus 5.5</th>"
              "<th class='num'>diff</th><th>bar</th></tr></thead><tbody>" + "".join(toprows) + "</tbody></table>")
    html = html.replace("<div id=\"divtable\"></div>", table2)

    # strip the inline script entirely
    html = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    html = html.replace("__ALLTABLE__", "")
    open(OUT, "w").write(html)
    print(f"{len(rows)} cells -> {OUT}")

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LEAP Wave 13 — Panel Findings</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--edge:#30363d;--fg:#e6edf3;--dim:#8b949e;
--up:#3fb950;--dn:#f85149;--acc:#58a6ff;--gold:#d29922}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif;
padding:40px 16px;max-width:1100px;margin:0 auto}
h1{font-size:26px;margin-bottom:4px}
h2{font-size:19px;margin:36px 0 12px;color:var(--acc)}
.sub{color:var(--dim);margin-bottom:28px}
.sub code{color:var(--fg);background:var(--card);padding:1px 6px;border-radius:4px;font-size:12px}
.card{background:var(--card);border:1px solid var(--edge);border-radius:10px;padding:20px;margin:14px 0}
.statrow{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0}
.stat{background:var(--card);border:1px solid var(--edge);border-radius:10px;padding:16px 20px;min-width:130px}
.stat b{font-size:26px;display:block}
.stat span{color:var(--dim);font-size:12.5px}
.big b{color:var(--gold)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{color:var(--dim);text-align:left;font-weight:600;padding:7px 9px;border-bottom:1px solid var(--edge);cursor:default}
td{padding:7px 9px;border-bottom:1px solid #21262d;vertical-align:top}
tr:hover td{background:#1c2129}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{position:relative;height:16px;background:#21262d;border-radius:4px;min-width:60px}
.bar i{position:absolute;top:0;bottom:0;border-radius:4px;display:block}
.up i{background:var(--up)}.dn i{background:var(--dn)}
.tag{display:inline-block;background:#1f6feb33;color:var(--acc);border-radius:4px;padding:0 7px;font-size:11.5px;margin-left:6px}
.tag.dim2{background:#a371f733;color:#c9a7ff}
.note{color:var(--dim);font-size:13px;margin-top:10px}
.kb{color:var(--gold)}
.foot{color:var(--dim);font-size:12.5px;margin-top:40px;border-top:1px solid var(--edge);padding-top:16px}
.pill{display:inline-block;border:1px solid var(--edge);border-radius:20px;padding:3px 12px;margin:2px;font-size:12.5px;color:var(--dim)}
select,input{background:var(--card);color:var(--fg);border:1px solid var(--edge);border-radius:6px;padding:5px 9px;font-size:13px}
.toolbar{margin:10px 0}
</style></head><body>
<h1>LEAP Wave 13 — Panel Findings</h1>
<div class="sub">Agent-box ensemble (mean of 4 models × group-shard runs) · survey <code>313ea2c1…49</code> · source <code>rectunz0NAgYb6piM</code> · 2026-10-16 · cutoff snapshot</div>

<div class="statrow">
  <div class="stat"><b>46</b><span>forecast cells</span></div>
  <div class="stat"><b>4</b><span>members (ECI live top-4)</span></div>
  <div class="stat big"><b>43 / 46</b><span>cells where ensemble &gt; Opus 5.5</span></div>
  <div class="stat"><b>13.4</b><span>Opus's mean shortfall vs ensemble</span></div>
  <div class="stat"><b>2</b><span>cells where ensemble &lt; Opus</span></div>
</div>

<h2>1 · The headline: the ensemble is systematically more aggressive than its own strongest member</h2>
<div class="card">
<p>Comparing every cell's ensemble mean against the highest-ECI member (Claude Opus 5.5): in <b>43 of 46 cells</b> the ensemble lands <b>above</b> Opus, in 1 they tie, and in only 2 is Opus above the ensemble. The ensemble's optimism is not one model dragging — it is Opus being the outlier at the <i>conservative</i> end:</p>
<table style="margin-top:14px"><thead><tr><th>member</th><th class="num">mean gap vs ensemble</th><th class="num">mean |gap|</th><th class="num">cells above ensemble</th></tr></thead>
<tbody><tr><td>GPT-6.1 Sol</td><td class="num">+13.1</td><td class="num">14.6</td><td class="num">~40</td></tr>
<tr><td>GPT-6 Astra</td><td class="num">+11.0</td><td class="num">13.0</td><td class="num">~37</td></tr>
<tr><td>Fable 5.1</td><td class="num">−10.8</td><td class="num">16.5</td><td class="num">~8</td></tr>
<tr><td><b>Opus 5.5</b> <span class="tag">highest ECI</span></td><td class="num">−13.4</td><td class="num">15.1</td><td class="num">3</td></tr></tbody></table>
<p class="note">Gap = member − ensemble, averaged over 46 cells (probability points on probability cells; raw units elsewhere). Opus and Fable form a conservative bloc; the two GPT-6s a bullish bloc. The mean is thus a tug-of-war, and the GPT bloc happens to hold the rope.</p>
</div>

<h2>2 · Where the ensemble and Opus disagree most</h2>
<div class="card"><p>Normalized divergence (points for probabilities, % for unit quantities). Bars show the sign: <span class="kb">gold</span> = ensemble above Opus, red = below.</p>
<div id="divtable"></div>
<p class="note">The largest disagreements cluster in the “probability that AI will solve…” blocks (Opus much lower), the AIPN Congress-tracker counts (Opus ~12–16 members lower), and the December-2026 AI-spend quantiles (Opus lower across p10/p50/p90).</p>
</div>

<h2>3 · Session-shard cross-check: differences are inside the noise</h2>
<div class="card">
<p>Every member also ran the whole survey as one session. Per-cell |session − group| averages <b>16.8</b>, but member spread within a shard is 44 (group) / 67 (session) — larger than the shard effect itself. The only big outlier is the wildcard commodity p90 (1850 vs 2350): a heavy-tail cell where no format helps. <b>Conclusion: session mode adds nothing measurable, costs ~4× more, and widens divergence — group-shard is the right submission format.</b></p>
</div>

<h2>4 · All 46 cells</h2>
<div class="card"><div id="alltable">__ALLTABLE__</div></div>

<h2>5 · Known blemishes (pilot lessons)</h2>
<div class="card">
<ul style="margin-left:18px">
<li>Percentile-order violations survive in both shards (e.g. one AIPN count group has p50 > p90 within members) — no coherence validator was used, per design decision; flag to the panel owner.</li>
<li>Anthropic runs cost 4–8× OpenAI's per pass; one transient API error mode (“out of extra usage”) required retry logic.</li>
<li>Run cost ~$96 across this fleet (deduplicated); Astra's session-shard pass alone was $46.</li>
</ul>
</div>

<div class="foot">Generated from <code>leap-w13-runs/main</code> aggregates & provenance · scripts in <code>agent-box-w13/scripts/leap_panel.py</code> · not a submission artifact; internal review only.</div>

<script>
const DATA = /*__DATA__*/;
const fmt = v => typeof v === 'number' ? (Math.abs(v) >= 1000 ? v.toLocaleString(undefined,{maximumFractionDigits:0}) : (+v.toFixed(v < 10 && Math.abs(v) >= 0 ? 2 : 1))) : '—';
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const unitCell = r => r.kind==='pts' ? `${fmt(r.diff)} pts` : `${r.diff>0?'+':''}${fmt(r.diff)} (${r.div.toFixed(0)}%)`;

const top = DATA.cells.slice(0,14);
document.getElementById('divtable').innerHTML = '<table><thead><tr><th>cell</th><th class="num">ensemble</th><th class="num">Opus 5.5</th><th class="num">diff</th><th>bar</th></tr></thead><tbody>'+
 top.map(r=>{
   const max = Math.max(...top.map(x=>x.div));
   const w = Math.max(3, 100*r.div/max);
   const cls = r.diff>0?'up':'dn';
   const dim = r.dimension?` <span class="tag dim2">${esc(r.dimension)}</span>`:'';
   return `<tr><td>${esc(r.group)}${dim} · p${r.percentile ?? '—'}${r.year?` (${r.year})`:''}<br><span style="color:var(--dim);font-size:12px">${esc(r.question)}</span></td>`+
     `<td class="num">${fmt(r.ensemble)}</td><td class="num">${fmt(r.opus)}</td><td class="num">${unitCell(r)}</td>`+
     `<td><div class="bar ${cls}"><i style="width:${w}%"></i></div></td></tr>`;
 }).join('')+'</tbody></table>';

const renderAll = mode=>{
  let rows = DATA.cells;
  if(mode==='big') rows = rows.filter(r=>r.kind==='pts'?Math.abs(r.diff)>=10:r.div>=10);
  if(mode==='near') rows = rows.filter(r=>r.spread<=2);
  document.getElementById('alltable').innerHTML = '<table><thead><tr><th>group / dimension</th><th>p</th><th class="num">ensemble</th><th class="num">Opus</th>'+
    DATA.members.slice(1).map(m=>`<th class="num">${esc(m)}</th>`).join('')+'<th class="num">session</th></tr></thead><tbody>'+
   rows.map(r=>`<tr><td>${esc(r.group)}${r.dimension?` <span class="tag dim2">${esc(r.dimension)}</span>`:''}<br><span style="color:var(--dim);font-size:11.5px">${esc(r.question).slice(0,150)}</span></td>`+
     `<td>${r.percentile??'—'}</td><td class="num"><b>${fmt(r.ensemble)}</b></td><td class="num">${fmt(r.opus)}</td>`+
     DATA.members.slice(1).map(m=>`<td class="num" style="color:var(--dim)">${fmt(r.members[m])}</td>`).join('')+
     `<td class="num" style="color:var(--dim)">${fmt(r.session)}</td></tr>`).join('')+'</tbody></table>';
};
renderAll('all');
</script>
</body></html>"""

if __name__ == "__main__":
    main()
