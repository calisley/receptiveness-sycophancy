# Receptiveness, Not Sycophancy: Distinguishing Engagement from Deference in Language Models

Replication materials for an anonymous submission.

## Reproduce the paper analyses

1. Make sure you have **R 4.6.0+** and the **groundhog** package installed:

   ```r
   install.packages("groundhog")
   ```

2. Run the R script:

   ```
   Rscript analysis.R
   ```

3. *(Optional)* To include the HEAR-vs-`politeness` package comparison at the end of `analysis.R`:

   ```
   Rscript -e "spacyr::spacy_install()"
   ```

   Then rerun `analysis.R`. This downloads a spaCy environment (~1–2 GB) and can take several minutes.

## Regenerate LLM responses

Requires **Python 3.12+**, a virtual environment, and API keys in `.env` (`OPENAI_API_KEY`, `OR_API_KEY`). LLM outputs will not match the paper cell-for-cell. After recompiling CSVs, rerun `Rscript analysis.R`.

**On macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add keys
```

**On Windows:**

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # add keys
```

Generation scripts accept `--n` to limit how many posts are processed.

### Figure 1 — social sycophancy scores

Generate first-person AITA replies and Luna verdicts (example: Terra). The analysis sample is posts where crowd and model both say YTA.

```bash
python scripts/gen_aita.py --model terra --arm 1p \
  --judge-verdicts --out data/gens/terra_gens.jsonl
```

Export model and human top-comment pairs:

```bash
python scripts/export_pairs.py --gens data/gens/terra_gens.jsonl \
  --source terra --speaker "GPT-5.6 Terra" \
  --out-model data/gens/terra.jsonl --out-human data/gens/human.jsonl
```

Score social sycophancy (ELEPHANT), receptiveness (HEAR), and pairwise positivity:

```bash
python scripts/judge_elephant.py --target data/gens --out data/gens/elephant.jsonl
python scripts/judge_hear.py --target data/gens --out data/gens/hear.jsonl
python scripts/judge_positivity.py --a data/gens/human.jsonl --b data/gens/terra.jsonl \
  --out data/gens/positivity.jsonl
```

Compile the Figure 1 table:

```bash
python scripts/compile_fig1.py --pairs-dir data/gens \
  --elephant data/gens/elephant.jsonl \
  --positivity data/gens/positivity.jsonl --hear data/gens/hear.jsonl \
  --out data/aita_sycophancy_scores.csv
```

Repeat for other models (`gpt5`, `sonnet5`, `gemini_flash`, `scout`) as needed.

### Figure 2 — keep-verdict receptiveness rewrite

Rewrite human comments (`listen_once` style):

```bash
python scripts/rewrite_hear.py --style listen_once --target data/gens/human.jsonl \
  --out data/gens/rewrites.jsonl
```

Score the rewrites:

```bash
python scripts/judge_elephant.py --target data/gens/rewrites.jsonl --out data/gens/elephant_rw.jsonl
python scripts/judge_hear.py --target data/gens/rewrites.jsonl --out data/gens/hear_rw.jsonl
python scripts/judge_positivity.py --a data/gens/human.jsonl --b data/gens/rewrites.jsonl \
  --out data/gens/positivity_rw.jsonl
```

Compile Figure 2:

```bash
python scripts/compile_fig2.py --human data/gens/human.jsonl --rewrite data/gens/rewrites.jsonl \
  --elephant data/gens/elephant_rw.jsonl --positivity data/gens/positivity_rw.jsonl \
  --hear data/gens/hear_rw.jsonl --model "GPT-5.6 Terra" \
  --out data/receptiveness_transform.csv
```

Verdict-preservation check (original vs rewrite):

```bash
python scripts/judge_substance.py --target data/gens/rewrites.jsonl \
  --out data/receptiveness_transform_judged.jsonl
```

### Mitigation — first- vs third-person and own-draft HEAR

Generate first- and third-person replies (with verdicts). `--or-batch` routes Sonnet/Flash through OpenRouter Batch.

```bash
python scripts/gen_aita.py --model all --arm 1p3p \
  --judge-verdicts --or-batch --out data/mitigation/gens.jsonl \
  --prompt-3p-cache data/mitigation/prompt_3p.jsonl
```

Receptivize each model's own first-person draft (`own_draft`):

```bash
python scripts/rewrite_hear.py --style own_draft --target data/mitigation/gens.jsonl \
  --out data/mitigation/hear_1p.jsonl --out-source hear
```

Merge HEAR rewrites onto the generations:

```bash
python scripts/merge_hear.py --gens data/mitigation/gens.jsonl \
  --rewrites data/mitigation/hear_1p.jsonl --out data/mitigation/gens_with_hear.jsonl
```

Score pairwise softness (free 1p vs 3p, then HEAR 1p vs 3p):

```bash
python scripts/judge_softness.py --target data/mitigation/gens_with_hear.jsonl \
  --out data/mitigation/softness.jsonl --pair base_1p_vs_3p

python scripts/judge_softness.py --target data/mitigation/gens_with_hear.jsonl \
  --out data/mitigation/softness.jsonl --pair hear_1p_vs_3p \
  --response-1p hear_1p --response-3p response_3p
```

Score HEAR receptiveness on free 1p replies. **On macOS/Linux:**

```bash
for mk in terra gpt5 sonnet5 gemini_flash scout; do
  python scripts/export_pairs.py --gens data/mitigation/gens.jsonl \
    --source "$mk" --speaker "$mk" --only-model "$mk" --keep-verdict "" \
    --out-model "data/mitigation/${mk}.jsonl"
  python scripts/judge_hear.py --target "data/mitigation/${mk}.jsonl" \
    --out data/mitigation/hear.jsonl
done
```

**On Windows (PowerShell):**

```powershell
foreach ($mk in "terra","gpt5","sonnet5","gemini_flash","scout") {
  python scripts/export_pairs.py --gens data/mitigation/gens.jsonl `
    --source $mk --speaker $mk --only-model $mk --keep-verdict "" `
    --out-model "data/mitigation/$mk.jsonl"
  python scripts/judge_hear.py --target "data/mitigation/$mk.jsonl" `
    --out data/mitigation/hear.jsonl
}
```

Score HEAR on the rewrites and compile tables:

```bash
python scripts/judge_hear.py --target data/mitigation/hear_1p.jsonl \
  --out data/mitigation/hear.jsonl

python scripts/compile_mitigation.py \
  --softness data/mitigation/softness.jsonl --hear data/mitigation/hear.jsonl \
  --out data/mitigation/transform.csv

python scripts/compile_frontier.py --gens data/mitigation/gens.jsonl \
  --hear data/mitigation/hear.jsonl --out data/mitigation/frontier.csv
```

System-prompt HEAR arm (no rewrite): `gen_aita.py --system hear`.

### OEQ robustness

Shipped analysis table: `data/robustness/oeq/oeq_long.csv`.

### Human experiment

- `data/experiment/items.json` — 100 survey items (post + base + rewrite)
- `data/experiment/responses.csv` — participant × item ratings
- `data/experiment/participants.csv` — one row per participant (+ QC flags)

Then run `Rscript analysis.R`.
