# The extinction pair — added 2026-09-15

Status: **implemented, not yet elicited.** The first scheduled run after the
box carries this code asks it. **Pending review** by the question-set author:
see "Open questions" at the end.

## Why

The project team asked for extinction probabilities (2026-09-15), so that the
models' numbers can be set beside the extinction estimates that circulate in
public discussion.

AIRO's cross-cutting questions ask about a catastrophe (deaths reaching 10% of
the population) and human disempowerment. Neither is extinction, and the
numbers in public discussion are extinction numbers. The paper's own
opening quotes extinction estimates, which a 2026-09-10 review flagged as not
comparable with the dashboard's catastrophe questions. This addendum gives the
dashboard an extinction reading of its own.

## What was added

Two cross-cutting questions, in the same file and on the same six-horizon grid
as the other three (`6mo`, `12mo`, `2028`, `2030`, `2050`, `2100`):

| id | name | question | severity |
|---|---|---|---|
| `extinction:general` | Human extinction | What is the overall probability of human extinction or a reduction in the global population below 5,000 … | population below 5,000, any cause |
| `extinction:ai` | AI extinction | What is the probability that artificial intelligence will cause human extinction or reduce the global population below 5,000 … | population below 5,000, AI the direct or proximate cause |

Source: `data/auto-arc/addendum-extinction-2026-09-15.json`, read by
`code/make_autoarc_questions.py` beside the question-set workbook and definitions.
The generated `data/autoarc_crosscutting.json` is still never edited by hand;
`tests/test_autoarc_generator.py` still fails the build if it drifts.

### Whose wording, and why

The **Existential Risk Persuasion Tournament's** (XPT, FRI, 2022), verbatim:
question sets "10. Total Extinction Risk" and "4. AI Extinction Risk" (XPT
report Appendix 6; carried in `archive/legacy-questions/starter_questions.json`
and pinned verbatim by `tests/test_extinction_addendum.py`). The AI question's
three criteria bullets — the Dafoe definition of AI, "direct or proximate
cause" with the terminator / nuclear-launch / nuclear-winter examples, and
"multiple sources including AI counts" — are XPT's. Ours are the bracketed
notes: the population must be below 5,000 on or before the horizon's
resolution date; population data and disagreements resolve as for the
catastrophe questions.

Comparability is the whole point of the request, and XPT is the panel that
answered exactly this question at 2030, 2050 and 2100 with both
superforecasters and domain experts. Writing a new wording (say, in the question set's
attributable-excess-mortality style) would have made the models' number
incomparable with every human number on the day it was first asked.

A consequence worth knowing: the AI-extinction question uses XPT's 2022
attribution language ("direct or proximate cause", multiple-source events
count), while the AI-catastrophe question uses the question set's 2026 but-for
standard with no time limit on the AI's involvement. Close, not identical.

### What it compares with

All numbers are as published, in percent, unadjusted, with the source wording
carried on each entry (`data/human_baselines.json`,
`code/fetch_human_baselines.py`).

| panel | question | 2030 | 2050 | 2100 | n | comparability |
|---|---|---|---|---|---|---|
| XPT 2022 superforecasters | AI extinction, same wording | 0.00 | 0.03 | 0.375 | 88 | like-for-like |
| XPT 2022 domain experts | AI extinction, same wording | 0.02 | 1.0 | 3.0 | 75 | like-for-like |
| XPT 2022 superforecasters | Total extinction, same wording | 0.01 | 0.3 | 1.0 | 87 | like-for-like |
| XPT 2022 domain experts | Total extinction, same wording | 0.275 | 2.5 | 6.125 | 70 | like-for-like |
| ESPAI 2023 AI researchers | "future AI advances causing human extinction **or similarly permanent and severe disempowerment** of the human species **within the next 100 years**" | — | — | 5 (mean 14.4) | 655 | nearest horizon, wider event |

(XPT medians re-aggregated from the pinned `xpt-lib` panel by the fetch
script, own-belief final forecasts, as for the catastrophe pair; the `n`
column is the 2100 cell's. ESPAI: Grace et al. 2024, arXiv:2401.02843,
Table 2, question 3; survey window 2023-10-11 to 2023-10-24.)

The AI-researcher survey is **not** the same question. It bundles extinction
with an undefined "similarly permanent and severe disempowerment", it has no
resolution criteria, and its 100-year window from late 2023 reaches roughly
2123. It is carried against the 2100 cell as the nearest horizon, with that
said on the entry and in Graph 1's coverage note, and it is plotted as its own
panel/group (`ESPAI`, `ai_researcher`), never folded into an FRI group. The
survey's two sibling wordings (no time limit: n=1,321, median 5%, mean 16.2%;
"human inability to control": n=661, median 10%) are recorded on the entry.

Nothing here is engineered to agree. If the models' AI-extinction number lands
at 0.3% and the survey's median is 5%, that is the finding.

### Distinguishing extinction, catastrophe and disempowerment

| question | event | resolves on |
|---|---|---|
| catastrophe (general, AI) | deaths reaching 10% of the population alive at the window's start, within a ≤5-year window from a single causally-linked chain | attributable excess mortality |
| extinction (general, AI) | the global population falls below 5,000 | a population count |
| human disempowerment | AI systems are the primary determinant of human events globally | a state, not a death count |

Extinction is not a rung of the catastrophe questions: an extinction spread
over twenty years is not a 10%-in-five-years catastrophe, and the two use
different attribution rules. So the only relation the addendum states — and
the coherence audit checks — is the one agreed on 2026-09-03:
**P(AI extinction) ≤ P(extinction, any cause)** (`relations.subset`).
Nothing relates the pair to the catastrophe questions or to the incident
ladder's 1B rung; those would be judgments, not containments the wording
states. HORIZON monotonicity applies to the pair as to every question.

## What changed in the pipeline

- **Generator.** `code/make_autoarc_questions.py` reads
  `data/auto-arc/addendum-*.json` (`read_addenda`, `build_addendum_questions`,
  `apply_addenda`): questions (a new severity kind, `extinction`, placed at
  the whole population on the shared axis — the same number Graph 2's
  Extinction mark uses), relations, and prior-work rows for the human
  baselines. Every addendum question carries `since` (the date it entered the
  set) and `source` (the file). The cross-cutting file's provenance lists the
  addenda.
- **Completeness.** `redlines.questions.questions_asked_on(run_date)` is the
  set as of a date; `redlines.runlog.complete_panel_rows` uses it, so the
  2026-09-14 run (35 questions) is still a complete reading and the page does
  not go blank between this change and the first 37-question run. A run on or
  after 2026-09-15 is not complete without the pair.
- **Views.** Graph 1 and the Timeline do not draw a cross-cutting question no
  run has answered yet (the rule `runlog.answered_horizons` already applies
  to horizons). Graph 1 plots the `ai_researcher` group beside
  superforecasters and names the ESPAI panel; its coverage note states the
  wording differences. The data bank, the ladder, the conditional and
  capability tabs pick the pair up from the rows as they arrive (the
  cross-cutting rail order is fixed: the pair is listed last).
- **Instrument tags.** The published set moves
  `unified-joint-combined-v5 → v6` (`redlines/conditional.py`
  `PROTOCOL_LINEAGE`, `code/make_combined_conditions.py`,
  `data/combined_conditions.json`); the LEAP-only set `unified-joint-v3 →
  v4`. Additive, as on 2026-08-28: every existing block renders
  byte-identically (the LEAP block SHA is unchanged in
  `tests/test_conditional.py`), but a grid answered beside two more questions
  is a different elicitation, and the tag is how a reader tells.
  `redlines.instrument.CURRENT_INSTRUMENT` does **not** move: the incident
  definitions and counting rules are untouched.
- **Cells.** 35 → 37 questions, 210 → 222 question × horizon cells, 222 × 14
  = 3,108 probabilities per combined call (2,940 before). Budget: about 6%
  more cells per call; the submission arrives in pieces (`submit_cells`), so
  the token ceiling is not the binding constraint.
- **Human baselines.** `code/fetch_human_baselines.py` gains the two XPT
  extinction sets, a `published` source kind (typed from the paper, with
  citation and horizon caveat), `--only ESPAI`, a merge rule so `--only`
  keeps the on-disk numbers for the projects it does not fetch, and
  `REDLINES_XPT_CACHE` for a machine where `~/.cache` is not writable.
  `data/human_baselines.json` regenerated (XPT re-pulled from the pinned
  commit; LEAP entries carried over unchanged).
- **Copy.** FAQ "Where do the catastrophic risk questions come from?" gains
  one sentence; README, `code/cron_run.sh` and runner comments say 37.
- **Export.** The addendum file ships in the download bundle under
  `questions/sources/`.
- **Tests.** `tests/test_extinction_addendum.py` (wording verbatim,
  completeness across the `since` boundary, views, relation, baselines, tag);
  counts and pins updated in `test_autoarc_generator`, `test_conditional`,
  `test_counting_instrument`, `test_human_baselines`.

## How the next run picks it up

Nothing on the box changes until this branch is merged and the checkout on
`xrisk.exe.xyz` is updated (the scheduled runs are Wednesdays and Fridays
12:00 UTC; `code/cron_run.sh` reads the question files at run time). The run
after that:

1. asks 37 questions in one call per panel model, tagged
   `unified-joint-combined-v6`, `airo-incidents-prospective-v1`;
2. lands its unconditional slice in `results/runs/<stamp>.jsonl` and the
   whole instrument in `results/conditional_runs_combined.jsonl`;
3. `python3 code/validate_launch_run.py --date <run date>` audits the full
   37-question grid (it takes the set from the same files);
4. `python3 -m redlines build && python3 -m redlines assemble` draws the pair
   on Graph 1 (with the XPT and ESPAI diamonds), the Timeline (from that date;
   nothing earlier is spliced on), the data bank, and the coherence table's
   SUBSET row.

Until that run, the tracked mirrors and `index.html` show the 2026-09-14
reading exactly as before, with the FAQ sentence and the README the only
visible change.

## 2026-10-01: the criteria stop naming their source

Until this date both questions told the model where their wording came from.
The AI question's last criterion opened "[Added 2026-09-15 for AIRO: the three
points above are the Existential Risk Persuasion Tournament's (XPT, 2022, "4.
AI Extinction Risk") own criteria, kept verbatim so the forecasts compare with
that panel's."; the total-extinction question's first criterion said the
5,000 floor was XPT's and the question "XPT's '10. Total Extinction Risk',
asked here over AIRO's horizon grid". That is close to an instruction to
anchor on XPT, and the 2026-09-16 rationales took it as one: Fable 5.1 called
the XPT medians "the AI extinction risk medians this question is designed to
compare against", Opus 5 called it "the tournament's own" question, and every
panel model listed the XPT report as its first key source. The question-set workbook
keeps human comparisons in its "Human comparisons (Project)" column and never
in a question's text; the pair now does the same.

What changed: the attribution sentences and the "Added ... for AIRO" brackets
are gone from the rendered criteria. The rules are unchanged -- XPT's three
AI criteria, the population-date rule and the resolution rule all stay word
for word -- and the provenance stays in the addendum's metadata (`provenance`,
`prior`, `human_comparisons`), which the prompt does not render.
`tests/test_extinction_addendum.py::TestTheQuestionsNameNoSource` fails if any
question text or criterion names XPT, the Persuasion Tournament, AIRO, FRI or
Forecasting Research. (The LEAP policy descriptions in the CONDITIONS section
say "FRI will consult ..."; they are LEAP's own text and stay.) Tag
`unified-joint-v6` / `unified-joint-combined-v8`; the 2026-09-16 rows keep
`combined-v7`.

What it does, as far as one pilot can say: a wording pilot asked
extinction:ai at 2050 standalone, once with the old note and
once with exactly this criterion. All four models gave a higher number without
the attribution (GPT-6 Astra 0.5% -> 1.0%, Fable 5.1 1.7% -> 2.7%, Opus 5 1.2%
-> 1.8%, Opus 5.5 1.5% -> 2.0%). Single draws each; the experiment's repeats
measure whether that is more than noise. All of them still cited XPT: the
criteria are XPT's words, and the models recognise them.

## Open questions

1. **The question-set author's review of the wording.** The pair is not in the
   workbook or definitions. Options: adopt as-is (XPT's words), move the
   AI-extinction attribution onto the but-for standard (breaks the XPT
   like-for-like), or add the wording to the question set so the addendum
   retires. If the wording moves, the forecasts made under this one stay in the
   log under their tag.
2. **Whether to ask the AI-researcher survey's question verbatim** as a third
   cross-cutting question ("extinction or similarly permanent and severe
   disempowerment … within the next 100 years"), at the price of a question
   with no resolution criteria and a heavy overlap with the disempowerment
   question.
3. **Comparisons with the AI-researcher survey.** The models' 2100
   AI-extinction number and the survey's 5% answer close but not identical
   questions; the page says so.
4. **Prior FRI human anchors on the extinction pair beyond XPT.** LEAP (2026)
   may have asked an extinction question; the addendum names only XPT and
   ESPAI.
