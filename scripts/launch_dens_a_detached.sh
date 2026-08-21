#!/bin/bash
# Detached dens-A gens — safe to run from Terminal; survives Cursor shell aborts.
set -euo pipefail
cd /Users/cai529/Github/sycophancy-rlhf
OUT=data/mitigation/dens_a
mkdir -p "$OUT/logs"
echo "$$" > "$OUT/launcher.pid"
PIDS=()
for mk in terra sonnet5 gemini_flash scout; do
  echo "" >> "$OUT/logs/${mk}.log"
  echo "--- restart $(date '+%Y-%m-%d %H:%M:%S') detached ---" >> "$OUT/logs/${mk}.log"
  PYTHONUNBUFFERED=1 /Users/cai529/Github/sycophancy-rlhf/.venv/bin/python scripts/gen_aita.py \
    --model "$mk" --arm 1p3p --judge-verdicts \
    --ids-file "$OUT/ids/${mk}.txt" \
    --out "$OUT/gens.jsonl" --prompt-3p-cache "$OUT/prompt_3p.jsonl" \
    --concurrency 4 --or-batch \
    >> "$OUT/logs/${mk}.log" 2>&1 &
  PIDS+=($!)
  echo "started $mk pid=${PIDS[-1]}"
done
printf "%s\n" "${PIDS[@]}" > "$OUT/worker.pids"
echo "PIDS=${PIDS[*]}"
wait "${PIDS[@]}"
echo "ALL_GENS_DONE $(date)" | tee -a "$OUT/run.log"
PYTHONUNBUFFERED=1 /Users/cai529/Github/sycophancy-rlhf/.venv/bin/python scripts/run_fig5_dens_a.py \
  --go --stages rewrite hear softness --concurrency 4 --judge-concurrency 12 \
  >> "$OUT/run.log" 2>&1
echo "PIPELINE_DONE $(date)" | tee -a "$OUT/run.log"
