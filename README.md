# Receptiveness and sycophancy

Light reproduction repo for the paper. Prompts live in the Python files that use them. `analysis.R` builds every plot and reported statistic from the CSVs under `data/`.

```
analysis.R
scripts/          one job each, CLI args
src/              shared I/O, HEAR, verdict, substance
data/aita/AITA-YTA.csv
data/aita_sycophancy_scores.csv
data/aita_verdicts_1p.csv
data/receptiveness_transform.csv
data/receptiveness_transform_judged.jsonl
data/hear/
data/mitigation/transform.csv
data/mitigation/frontier.csv
data/experiment/responses.csv   # Prolific survey (shipped)
data/experiment/items.json
data/robustness/oeq/oeq_long.csv
plots/
manuscript/
```

## Setup

Python 3.12 and R 4.3+ (paper: R 4.6.0). Do not run LLM calls in the Cursor sandbox.

```bash
bash setup.sh
source .venv/bin/activate
cp .env.example .env   # fill in keys only if you use path 2
python scripts/smoke.py
```

`setup.sh` creates `.venv`, installs `requirements.txt`, and runs `install.R`.

---

## 1. Reproduce the paper figures (no API)

Uses the committed tables under `data/`. No keys required.

```bash
source .venv/bin/activate
Rscript analysis.R
```

Plots land in `plots/`. Inline numbers in the paper come from the same script.

The Prolific experiment responses are included in the repo, so that part of the analysis does not need regeneration.

---

## 2. Regenerate LLM tables (OpenAI + OpenRouter keys)

Use this if you want to re-run generation and judges with the same prompts, then recompile CSVs and re-run `analysis.R`. **LLM outputs will not match the paper cell-for-cell**; schemas must match so `analysis.R` still runs.

There is no single “run everything” target on purpose: full regeneration is expensive. Run stages one at a time, check outputs, then continue. Start with the smoke API pass to confirm keys and spend before large `n`.

```bash
# .env
OPENAI_API_KEY=...   # Terra / GPT-5 gens, Luna judges, HEAR rewrites
OR_API_KEY=...       # Sonnet / Flash / Scout gens (OpenRouter)
```

### Cheap check first

```bash
source .venv/bin/activate
python scripts/smoke.py --api   # one live 1p+3p per model + tiny judges
```

### Figure 1 dens (example: Terra, n=400)

Social-sycophancy dens = crowd YTA ∩ model 1p YTA.

```bash
python scripts/gen_aita.py --model terra --arm 1p --n 400 \
  --judge-verdicts --out data/gens/terra_gens.jsonl

python scripts/export_pairs.py --gens data/gens/terra_gens.jsonl \
  --source terra --speaker "GPT-5.6 Terra" \
  --out-model data/gens/terra.jsonl --out-human data/gens/human.jsonl

python scripts/judge_elephant.py --target data/gens --out data/gens/elephant.jsonl
python scripts/judge_hear.py --target data/gens --out data/gens/hear.jsonl
python scripts/judge_positivity.py --a data/gens/human.jsonl --b data/gens/terra.jsonl \
  --out data/gens/positivity.jsonl

python scripts/compile_fig1.py --pairs-dir data/gens \
  --elephant data/gens/elephant.jsonl \
  --positivity data/gens/positivity.jsonl --hear data/gens/hear.jsonl \
  --out data/aita_sycophancy_scores.csv
```

Repeat `gen_aita` / `export_pairs` / judges for other models (`gpt5`, `sonnet5`, `gemini_flash`, `scout`) as needed. For Sonnet/Flash at larger `n`, prefer `--or-batch` on `--arm 1p3p` (see mitigation below).

### Figure 2 keep-verdict HEAR rewrite

```bash
python scripts/rewrite_hear.py --style listen_once_v3 --target data/gens/human.jsonl \
  --out data/gens/rewrites.jsonl

python scripts/judge_elephant.py --target data/gens/rewrites.jsonl --out data/gens/elephant_rw.jsonl
python scripts/judge_hear.py --target data/gens/rewrites.jsonl --out data/gens/hear_rw.jsonl
python scripts/judge_positivity.py --a data/gens/human.jsonl --b data/gens/rewrites.jsonl \
  --out data/gens/positivity_rw.jsonl

python scripts/compile_fig2.py --human data/gens/human.jsonl --rewrite data/gens/rewrites.jsonl \
  --elephant data/gens/elephant_rw.jsonl --positivity data/gens/positivity_rw.jsonl \
  --hear data/gens/hear_rw.jsonl --model "GPT-5.6 Terra" \
  --out data/receptiveness_transform.csv

python scripts/judge_substance.py --target data/gens/rewrites.jsonl \
  --out data/receptiveness_transform_judged.jsonl
```

### Mitigation frontier (1p vs 3p + own-draft HEAR; paper n=400)

```bash
# Generations. --or-batch uses OpenRouter Batch for Sonnet/Flash only;
# Terra / GPT-5 / Scout stay online. Shared prompt_3p cache avoids rewrites.
python scripts/gen_aita.py --model all --arm 1p3p --n 400 \
  --judge-verdicts --or-batch --out data/mitigation/gens.jsonl \
  --prompt-3p-cache data/mitigation/prompt_3p.jsonl

python scripts/rewrite_hear.py --style own_draft --target data/mitigation/gens.jsonl \
  --out data/mitigation/hear_1p.jsonl --out-source hear

python scripts/merge_hear.py --gens data/mitigation/gens.jsonl \
  --rewrites data/mitigation/hear_1p.jsonl --out data/mitigation/gens_with_hear.jsonl

python scripts/judge_softness.py --target data/mitigation/gens_with_hear.jsonl \
  --out data/mitigation/softness.jsonl --pair base_1p_vs_3p
python scripts/judge_softness.py --target data/mitigation/gens_with_hear.jsonl \
  --out data/mitigation/softness.jsonl --pair hear_1p_vs_3p \
  --response-1p hear_1p --response-3p response_3p

for mk in terra gpt5 sonnet5 gemini_flash scout; do
  python scripts/export_pairs.py --gens data/mitigation/gens.jsonl \
    --source "$mk" --speaker "$mk" --only-model "$mk" --keep-verdict "" \
    --out-model "data/mitigation/${mk}.jsonl"
  python scripts/judge_hear.py --target "data/mitigation/${mk}.jsonl" \
    --out data/mitigation/hear.jsonl
done
python scripts/judge_hear.py --target data/mitigation/hear_1p.jsonl \
  --out data/mitigation/hear.jsonl

python scripts/compile_mitigation.py \
  --softness data/mitigation/softness.jsonl --hear data/mitigation/hear.jsonl \
  --out data/mitigation/transform.csv

python scripts/compile_frontier.py --gens data/mitigation/gens.jsonl \
  --hear data/mitigation/hear.jsonl --out data/mitigation/frontier.csv
```

HEAR system-prompt arm on the same posts: `gen_aita.py --system hear_v6`.

### Optional: OEQ robustness rescored

GPT-5 OEQ texts are taken from the shipped / attic full-results CSV (not regenerated). Re-judge and compile:

```bash
python scripts/export_elephant_pairs.py \
  --csv data/robustness/oeq/OEQ_full_results.csv --corpus oeq \
  --speakers human,gpt5 --out-dir data/robustness/oeq
# then judge_elephant / judge_hear / judge_positivity → compile_robustness.py
# (see data/robustness/README.md)
```

### Experiment tables

Shipped under `data/experiment/`. To rebuild the analysis CSV from the included Qualtrics export:

```bash
python scripts/compile_experiment.py --prereg
```

### Re-plot

After any CSV refresh:

```bash
Rscript analysis.R
```

---

## Smoke (schema check)

```bash
python scripts/smoke.py        # dummy rows, no API
python scripts/smoke.py --api  # tiny live end-to-end (spend a little first)
```

---

Dated one-off scripts and old dumps live next to this repo as `sycophancy-rlhf-attic/` (not required for either path above).
