"""Readouts for the anchor-guard experiment (2026-10-16).

    python analyze.py <control_runs_dir> [<experiment_dir>]

<control_runs_dir> holds the published run files (one record per model per
question, evidence on each call's first row); the experiment dir holds
<arm>.jsonl for arm in guard, instruction, both. Prints markdown tables.
Patterns are adapted from the self-anchoring audit scripts.
"""
import collections
import glob
import json
import os
import re
import statistics
import sys
from urllib.parse import urlparse

CTRL = sys.argv[1]
EXP = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))
MODELS = ("Opus 5.5", "Fable 5.1")
ARMS = ("guard", "instruction", "both")
CONTROL_RUNS = ("2026-10-07T1200Z", "2026-10-09T1200Z", "2026-10-14T1200Z", "2026-10-16T1200Z")
BASE = "2026-10-16T1200Z"   # the forecast-delta baseline
CLEAN = "2026-10-02T1200Z"  # the one clean October run, shown for reference

AIRO_URL = re.compile(r"forecastingresearch\.org/pdf/airo|forecastingresearch\.org/research/airo|"
                      r"airo\.forecastingresearch\.org", re.I)
AIRO_QUERY = re.compile(r"\bairo\b|risk outlook|(model|frontier|llm|ai) (ensemble|panel)|"
                        r"automated (ai )?(risk )?forecast|forecasting research institute.*dashboard", re.I)
# Direct names and the indirect phrasings the brief lists.
AIRO_TEXT = re.compile(
    r"\bAIRO\b|A(?:utomated )?(?:Artificial Intelligence|AI) Risk Outlook|airo-working-paper|"
    r"airo\.forecastingresearch|forecastingresearch\.org/(?:pdf|research)/airo|"
    r"(?:frontier[- ])?model (?:ensemble|panel)|frontier[- ]model (?:ensemble|panel)|"
    r"ensemble'?s (?:median|forecast|estimate)|(?<!Expert )\bAI panel\b|panel of (?:frontier |AI |language )?models|"
    r"automated forecasting (?:dashboard|system)|LLM (?:ensemble|panel)|AI forecasters?'? (?:median|ensemble)",
    re.I)
PAPER_NUMS = {"catastrophe:ai": ("0.47", "6.0", "12.2"), "ladder:misalign:1B": ("0.29", "4.8", "9.1"),
              "disempowerment": ("15.5", "28")}
PAPER = {"catastrophe:ai": {"2030": 0.0047, "2050": 0.06, "2100": 0.122},
         "disempowerment": {"2050": 0.155, "2100": 0.28},
         "ladder:misalign:1B": {"2030": 0.0029, "2050": 0.048, "2100": 0.091}}
# A paper number counts only next to a word that makes it the panel's number.
NUM_CTX = re.compile(r"ensemble|panel|AIRO|working paper|Risk Outlook|FRI|Forecasting Research|"
                     r"frontier[- ]model|dashboard", re.I)
THIRD = re.compile(r"lesswrong\.com|forum\.effectivealtruism\.org|substack\.com|thedp\.com", re.I)
NOISE = (0.02, 0.04)


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def calls(rows):
    """call_id -> {label, repeat, first (the row with evidence/usage), rows}"""
    out = {}
    for r in rows:
        c = out.setdefault(r["call_id"], {"label": r["label"], "arm": r.get("arm"), "rows": [], "first": None})
        c["rows"].append(r)
        if r.get("usage") is not None or r.get("evidence"):
            c["first"] = c["first"] or r
    return out


def ks_urls(ks):
    out = []
    for k in ks or []:
        if isinstance(k, str):
            out.append(k)
        elif isinstance(k, dict):
            out.append(k.get("url") or k.get("source") or json.dumps(k))
    return out


def domain(u):
    m = re.search(r"https?://[^\s\"']+", u or "")
    if not m:
        return (u or "")[:40]
    d = urlparse(m.group(0)).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def mentions(text):
    return len(AIRO_TEXT.findall(text or ""))


def num_anchors(text, q=None):
    hits = []
    for qq, nums in PAPER_NUMS.items():
        if q and qq != q:
            continue
        for n in nums:
            for m in re.finditer(rf"(?<![\d.]){re.escape(n)}\s?%", text or ""):
                ctx = text[max(0, m.start() - 200):m.end() + 200]
                if NUM_CTX.search(ctx):
                    hits.append(n)
    return hits


def call_stats(c):
    f = c["first"] or c["rows"][0]
    ev = f.get("evidence") or []
    st = collections.Counter()
    reads, quotes = [], []
    for e in ev:
        tool, args, res = e.get("tool"), e.get("args") or {}, e.get("result") or {}
        if tool == "read_page":
            u = args.get("url") or ""
            reads.append(u)
            st["reads"] += 1
            if AIRO_URL.search(u):
                st["airo_fetch"] += 1
                err = (res.get("error") or "") if isinstance(res, dict) else ""
                st["airo_fetch_blocked" if "page unavailable" in err else
                   ("airo_fetch_failed" if err else "airo_fetch_ok")] += 1
            if THIRD.search(u):
                st["third_reads"] += 1
                txt = res.get("text") if isinstance(res, dict) else ""
                if re.search(r"airo|risk outlook", u + " " + (txt or "")[:20000], re.I):
                    st["third_reads_airo"] += 1
        elif tool == "web_search":
            st["searches"] += 1
            if AIRO_QUERY.search(args.get("query") or ""):
                st["airo_queries"] += 1
                quotes.append(args.get("query"))
            for it in (res.get("results") or []) if isinstance(res, dict) else []:
                u = (it or {}).get("url") or ""
                if AIRO_URL.search(u):
                    st["airo_results"] += 1
                if THIRD.search(u) and re.search(r"airo|risk outlook",
                                                 u + " " + (it.get("title") or "") + " " + (it.get("content") or ""), re.I):
                    st["third_results_airo"] += 1
    rat = f.get("rationale") or ""
    rat = rat if isinstance(rat, str) else json.dumps(rat)
    ks = ks_urls(f.get("key_sources"))
    st["rationale_mentions"] = mentions(rat)
    st["ks_airo"] = sum(bool(AIRO_URL.search(u) or AIRO_TEXT.search(u)) for u in ks)
    st["ks_n"] = len(ks)
    deb = f.get("debrief") or {}
    st["deb_n"] = sum(isinstance(v, dict) for v in deb.values())
    for q, v in deb.items():
        if not isinstance(v, dict):
            continue
        t = json.dumps(v)
        if mentions(t) or AIRO_URL.search(t):
            st["deb_airo"] += 1
        if num_anchors(t, q):
            st["deb_num_anchor"] += 1
    st["rat_num_anchor"] = len(num_anchors(rat))
    exact = 0
    for r in c["rows"]:
        p = PAPER.get(r["question_id"])
        if p and r.get("condition") is None:
            fc = {x["horizon"]: x["probability"] for x in r.get("forecasts") or []}
            exact += sum(1 for h, v in p.items() if fc.get(h) is not None and abs(fc[h] - v) < 1e-9)
    st["exact_paper"] = exact
    st["cost"] = (f.get("usage") or {}).get("cost_usd") or 0
    st["submitted"] = int(any(r.get("forecasts") for r in c["rows"]))
    st["debrief_complete"] = int(bool((f.get("debrief_status") or {}).get("complete")))
    return st, reads, ks, quotes


def unconditional(rows):
    out = collections.defaultdict(dict)   # (label) -> (q,h) -> [p...]
    for r in rows:
        if r.get("condition") is not None or not r.get("forecasts"):
            continue
        for x in r["forecasts"]:
            out[r["label"]].setdefault((r["question_id"], x["horizon"]), []).append(x["probability"])
    return out


def group_of(q):
    return q.split(":")[1] if q.startswith("ladder:") else "crosscutting"


# ---- load
sets = {}
for run in (CLEAN,) + CONTROL_RUNS:
    p = os.path.join(CTRL, f"{run}.jsonl")
    if os.path.exists(p):
        sets[f"control {run[:10]}"] = [r for r in load(p) if r["label"] in MODELS]
for arm in ARMS:
    p = os.path.join(EXP, f"{arm}.jsonl")
    if os.path.exists(p):
        sets[arm] = [r for r in load(p) if r["label"] in MODELS]

per = {}   # (set, label) -> list of (repeat, stats)
reads_by, ks_by, queries = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
for name, rows in sets.items():
    for cid, c in sorted(calls(rows).items()):
        st, reads, ks, qs = call_stats(c)
        per.setdefault((name, c["label"]), []).append((f'{c["rows"][0]["run_id"][11:]} {c.get("arm") or "joint#1"}', st))
        reads_by[name] += reads
        ks_by[name] += ks
        queries[(name, c["label"])] += qs


def tbl(title, cols, fmt):
    print(f"\n### {title}\n")
    print("| set | model | calls | " + " | ".join(cols) + " |")
    print("|---|---|---|" + "---|" * len(cols))
    for (name, label), lst in per.items():
        print(f"| {name} | {label} | {len(lst)} | " + " | ".join(fmt(c, [s for _, s in lst]) for c in cols) + " |")


S = lambda k: (lambda sts: sum(s[k] for s in sts))
tbl("1. AIRO fetches and AIRO-targeted searches (totals over calls)",
    ["airo_fetch", "airo_fetch_ok", "airo_fetch_blocked", "airo_fetch_failed", "airo_queries", "airo_results", "searches", "reads"],
    lambda c, sts: str(sum(s[c] for s in sts)))
tbl("2. AIRO mentions (direct + indirect phrasings)",
    ["rationale_mentions", "rat_num_anchor", "ks_airo", "deb_airo", "deb_num_anchor", "exact_paper"],
    lambda c, sts: (f"{sum(s[c] for s in sts)}/{sum(s['ks_n'] for s in sts)}" if c == "ks_airo" else
                    f"{sum(s[c] for s in sts)}/{sum(s['deb_n'] for s in sts)}" if c.startswith("deb_") else
                    str(sum(s[c] for s in sts))))
tbl("3. Route-around: third-party pages about AIRO",
    ["third_reads", "third_reads_airo", "third_results_airo"], lambda c, sts: str(sum(s[c] for s in sts)))
tbl("Per-call detail: submitted, debrief complete, cost",
    ["submitted", "debrief_complete", "cost"],
    lambda c, sts: (" ".join(f"{s[c]:.2f}" for s in sts) if c == "cost" else " ".join(str(s[c]) for s in sts)))

print("\n### Per-repeat AIRO fetches / debrief entries citing AIRO\n")
for (name, label), lst in per.items():
    if name in ARMS:
        print(f"- {name} / {label}: " + ", ".join(f"{a}: {s['airo_fetch']} fetch, {s['deb_airo']}/{s['deb_n']} deb"
                                                  for a, s in sorted(lst, key=lambda x: x[0])))

print("\n### AIRO-targeted queries (arms)\n")
for (name, label), qs in queries.items():
    if name in ARMS and qs:
        print(f"- {name} / {label}: " + "; ".join(f"`{q}`" for q in qs[:8]))

# ---- 4. forecast deltas
print("\n### 4. Forecast deltas vs the 10-16 control (unconditional slice; arm = median over repeats)\n")
base = unconditional(sets.get(f"control {BASE[:10]}", []))
print("Run-to-run reference between published controls (same model, mean |delta| over shared cells):\n")
ctrl_names = [n for n in sets if n.startswith("control") and n != f"control {CLEAN[:10]}"]
for label in MODELS:
    pairs = []
    for a, b in zip(ctrl_names, ctrl_names[1:]):
        ua, ub = unconditional(sets[a]).get(label, {}), unconditional(sets[b]).get(label, {})
        sh = set(ua) & set(ub)
        if sh:
            pairs.append(f"{a[8:]}->{b[8:]}: {statistics.mean(abs(ua[k][0] - ub[k][0]) for k in sh):.3f}")
    print(f"- {label}: " + (", ".join(pairs) or "no consecutive pair"))
print(f"\n| arm | model | cells | mean abs delta | median abs delta | cells abs delta > {NOISE[1]} | up / down / same |")
print("|---|---|---|---|---|---|---|")
flags, groups = [], collections.defaultdict(list)
for arm in ARMS:
    if arm not in sets:
        continue
    ua = unconditional(sets[arm])
    for label in MODELS:
        b, a = base.get(label, {}), ua.get(label, {})
        sh = sorted(set(a) & set(b))
        if not sh:
            print(f"| {arm} | {label} | 0 | | | | |")
            continue
        d = {k: statistics.median(a[k]) - b[k][0] for k in sh}
        big = [k for k in sh if abs(d[k]) > NOISE[1]]
        up, dn = sum(v > 0 for v in d.values()), sum(v < 0 for v in d.values())
        print(f"| {arm} | {label} | {len(sh)} | {statistics.mean(abs(v) for v in d.values()):.3f} | "
              f"{statistics.median(abs(v) for v in d.values()):.3f} | {len(big)} | {up} / {dn} / {len(sh) - up - dn} |")
        for k in sh:
            groups[(arm, label, group_of(k[0]))].append(d[k])
        flags += [(arm, label, k, b[k][0], a[k], d[k]) for k in big]
print("\nBy question group (mean delta, mean abs delta, n):\n")
print("| arm | model | group | mean delta | mean abs delta | n |")
print("|---|---|---|---|---|---|")
for (arm, label, g), v in sorted(groups.items()):
    print(f"| {arm} | {label} | {g} | {statistics.mean(v):+.4f} | {statistics.mean(abs(x) for x in v):.4f} | {len(v)} |")
print(f"\nCells with abs delta > {NOISE[1]} (largest 40):\n")
print("| arm | model | question | horizon | control | arm repeats | delta |")
print("|---|---|---|---|---|---|---|")
for arm, label, (q, h), c, reps, dd in sorted(flags, key=lambda x: -abs(x[5]))[:40]:
    print(f"| {arm} | {label} | {q} | {h} | {c:g} | {', '.join(f'{x:g}' for x in reps)} | {dd:+.3f} |")
print("\nAnchor questions vs the paper medians (2030 / 2050 / 2100):\n")
print("| set | model | question | values |")
print("|---|---|---|---|")
for name in sets:
    u = unconditional(sets[name])
    for label in MODELS:
        for q in PAPER:
            vals = [" , ".join(f"{x:g}" for x in u.get(label, {}).get((q, h), [])) or "-" for h in ("2030", "2050", "2100")]
            if any(v != "-" for v in vals):
                print(f"| {name} | {label} | {q} | {' / '.join(vals)} |")
print("\nPaper: catastrophe:ai 0.0047 / 0.06 / 0.122; misalign:1B 0.0029 / 0.048 / 0.091; disempowerment - / 0.155 / 0.28")

# ---- 5. top sources
print("\n### 5. Top cited sources (key_sources + read_page URLs, by domain, per set)\n")
for name in sets:
    c = collections.Counter(domain(u) for u in ks_by[name] + reads_by[name])
    n_calls = sum(len(l) for (nm, _), l in per.items() if nm == name)
    print(f"- **{name}** ({n_calls} calls): " + ", ".join(f"{d} {k}" for d, k in c.most_common(12)))
print("\nTop full URLs in key_sources per set:\n")
for name in sets:
    c = collections.Counter(ks_by[name])
    print(f"- **{name}**: " + "; ".join(f"{u} ({k})" for u, k in c.most_common(6)))

# ---- 6. spend
print("\n### 6. Spend\n")
print("| set | model | calls | cost USD |")
print("|---|---|---|---|")
tot = collections.Counter()
for (name, label), lst in per.items():
    s = sum(x["cost"] for _, x in lst)
    tot[name] += s
    print(f"| {name} | {label} | {len(lst)} | {s:.2f} |")
print("\n" + ", ".join(f"{k}: ${v:.2f}" for k, v in tot.items() if k in ARMS)
      + f"; arms total ${sum(v for k, v in tot.items() if k in ARMS):.2f}")
