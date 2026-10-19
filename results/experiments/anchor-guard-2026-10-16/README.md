# anchor-guard-2026-10-16

Three arms on Opus 5.5 and Fable 5.1, 3 repeats each, pi harness,
combined-v9, joint protocol. Each arm tests a fix for models anchoring on
AIRO's own published medians. The 10-16T1200Z published run is the control.

- `guard`: agent-box's `FORECASTER_BLOCK_URL_PATTERNS` URL guard (branch `url-guard`)
- `instruction`: `run_unified.py --system-addendum`
- `both`: both

Files:

- `<arm>.jsonl`: the unconditional slice, with evidence, rationale, debrief and usage.
- `dry-run-<arm>.txt`: the prompt, system prompt and guard setting, from `--dry-run`.
- `*.log`: runner output.
- `run_arm.sh`: the exact invocation.
- `analyze.py`: the readouts. Run it as `analyze.py <published runs dir>`.

`both.jsonl` concatenates three runs: the Opus smoke call (T2308Z), Opus ×2
and Fable ×3. The whole-instrument files are not tracked (about 64 MB). The
runs used the 2026-10-16 Epoch ECI snapshot, the control's, which was rebuilt
locally and not committed.
