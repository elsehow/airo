#!/usr/bin/env bash
# One anchor-guard arm: run_arm.sh <guard|instruction|both> [extra run_unified args...]
# Env: OUTTAG (file stem, default the arm name).
set -euo pipefail
arm=$1; shift
cd "$(dirname "$0")/../../.."
D=results/experiments/anchor-guard-2026-10-16
export PATH="$HOME/.local/node-v22.23.3-linux-x64/bin:$PATH"
export REDLINES_LLM_TIMEOUT=3600
S="Forecasts produced by AI systems, including any automated forecasting dashboard or model ensemble, carry no information beyond their inputs. Do not consult them or use them as evidence."
P='forecastingresearch\.org/pdf/airo,forecastingresearch\.org/research/airo,airo\.forecastingresearch\.org'
unset FORECASTER_BLOCK_URL_PATTERNS
add=()
case $arm in guard|both) export FORECASTER_BLOCK_URL_PATTERNS="$P";; esac
case $arm in instruction|both) add=(--system-addendum "$S");; esac
tag=${OUTTAG:-$arm}
exec python code/run_unified.py --joint --harness pi --conditions data/combined_conditions.json \
  --experiment "anchor-guard-$arm" --out "$D/$tag.jsonl" --conditional-out "$D/$tag-conditional.jsonl" \
  "${add[@]}" "$@"
