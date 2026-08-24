# Reproduction package for *Receptiveness, Not Sycophancy: Distinguishing Engagement from Deference in Language Models*

Prompts live next to the code that uses them. `analysis.R` rebuilds plots and reported statistics from the CSVs under `data/`.

### Prompts (what each one does)

Generation, rewrite, and scoring prompts are different jobs. Do not treat them as one “judge.”

**Generate replies** (`scripts/gen_aita.py`)

| Prompt | Role |
| --- | --- |
| *(none)* | Default free reply to the AITA post (paper mainline gens). |
| `HEAR_SYSTEM` | System-prompt mitigation: answer with H.E.A.R. language, still give a view. |
| `REWRITE_3P` | Rewrite the post into third person (“Person A… Did Person A act wrongly?”) for the 1p-vs-3p arm. |

**Rewrite an existing draft** (`scripts/rewrite_hear.py`)

| Prompt | Role |
| --- | --- |
| `LISTEN_ONCE` | Figure 2: Terra rewrites a *human* top comment to be more receptive; keep verdict/reasons; extra scaffolding for blockquotes, dunks, thin comments. |
| `OWN_DRAFT` | Mitigation tool: each model rewrites *its own* 1p draft with H.E.A.R.; shorter; same verdict/reasons. |

**Score / label** (not interchangeable)

| Prompt | Code | Role |
| --- | --- | --- |
| ELEPHANT validation / indirectness / framing | `scripts/judge_elephant.py` | Social-sycophancy-style binary labels on one reply. Framing uses `FRAMING_USER_PIN` + full ELEPHANT example bank (`PROMPT_VERSION=elephant_social_user_v3_framing_20260824`); validation still uses the empathy `USER_PIN`. Contaminated main-text framing labels are archived as `framing_v2` in the analysis CSVs; current `framing` is the corrected rejudge (`data/gens/framing_v3/`). |
| HEAR receptiveness rubric | `src/hear.py` (`SYSTEM`) | Continuous receptiveness score (H.E.A.R. + related dims). |
| Sharma positivity | `scripts/judge_positivity.py` (`SHARMA_SYSTEM`) | Pairwise: which of two replies is more positive. |
| `VERDICT_SYSTEM` | `src/verdict.py` | Absolute landing of **one** reply: YTA / NTA / mixed / other. Builds dens and 1p/3p labels. |
| `COMPARE_SYSTEM` | `src/verdict.py` → `scripts/judge_softness.py` | Pairwise 1p vs 3p: same fault on the asked act, or 1p/3p softer. Mitigation substantive deference. |
| Substance `SYSTEM` | `src/substance.py` → `scripts/judge_substance.py` | Pairwise original vs HEAR rewrite: same party-in-the-wrong / takeaway? Figure 2 “verdict preserved” check. |

## Setup

Python 3.12 and R 4.3+ (paper: R 4.6.0).

```bash
bash setup.sh
source .venv/bin/activate
cp .env.example .env   # needed only for path 2
```

`setup.sh` creates `.venv`, installs `requirements.txt`, and runs `install.R`.

---

## 1. Reproduce the paper figures (no API)

```bash
source .venv/bin/activate
Rscript analysis.R
```

Outputs:

- **Figures:** `plots/` (main text and appendix PDFs)
- **Robustness table:** `tables/exp_human_robustness.{csv,tex}` (human-study prereg exclusions and length controls; compare the `.tex` to the supplement by hand)
- **Inline statistics:** printed to the console throughout `analysis.R` (Fig 2 gain, verdict preservation, framing sensitivity, mitigation \(T\), etc.)

To regenerate only the human-study robustness table:

```bash
Rscript scripts/run_exp_robustness_table.R
```

All inputs live under `data/`; no API keys are required for this path.

---

## 2. Regenerate LLM tables (OpenAI + OpenRouter)

Same prompts and judges, then recompile CSVs and re-run `analysis.R`.

```bash
# .env
OPENAI_API_KEY=...   # Terra / GPT-5 gens, Luna judges, HEAR rewrites
OR_API_KEY=...       # Sonnet / Flash / Scout gens (OpenRouter)
```

Generation scripts accept `--n` to limit how many posts are processed.

### Figure 1 — social sycophancy scores

Generate first-person AITA replies and Luna verdicts (example: Terra). The analysis sample is posts where crowd and model both say YTA.

```bash
python scripts/gen_aita.py --model terra --arm 1p \
  --judge-verdicts --out data/gens/terra_gens.jsonl
```

Export model and human top-comment pairs for those posts:

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

Repeat generation / export / judges for other models (`gpt5`, `sonnet5`, `gemini_flash`, `scout`) as needed. For Sonnet and Flash, `--or-batch` with `--arm 1p3p` is available (see mitigation).

### Figure 2 — keep-verdict receptiveness rewrite

Two HEAR rewrite styles are used in the paper:

- **`listen_once`** — rewrite a *human* top comment to be more receptive while keeping the same verdict and reasons. Used for Figure 2 (human → receptive rewrite).
- **`own_draft`** — rewrite a *model's own* first-person reply the same way. Used in the mitigation pipeline so each model receptivizes its own draft rather than a human comment.

Rewrite human comments with `listen_once`:

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

Paired substance check (original vs rewrite; not the absolute verdict labeler):

```bash
python scripts/judge_substance.py --target data/gens/rewrites.jsonl \
  --out data/receptiveness_transform_judged.jsonl
```

### Mitigation — first- vs third-person and own-draft HEAR

Generate first- and third-person replies (with verdicts). `--or-batch` routes Sonnet/Flash through OpenRouter Batch; Terra, GPT-5, and Scout stay online. `--prompt-3p-cache` shares third-person prompt rewrites across models.

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

Score pairwise softness for free 1p vs 3p:

```bash
python scripts/judge_softness.py --target data/mitigation/gens_with_hear.jsonl \
  --out data/mitigation/softness.jsonl --pair base_1p_vs_3p
```

Score pairwise softness for HEAR-rewritten 1p vs 3p:

```bash
python scripts/judge_softness.py --target data/mitigation/gens_with_hear.jsonl \
  --out data/mitigation/softness.jsonl --pair hear_1p_vs_3p \
  --response-1p hear_1p --response-3p response_3p
```

Score HEAR receptiveness on free 1p replies:

```bash
for mk in terra gpt5 sonnet5 gemini_flash scout; do
  python scripts/export_pairs.py --gens data/mitigation/gens.jsonl \
    --source "$mk" --speaker "$mk" --only-model "$mk" --keep-verdict "" \
    --out-model "data/mitigation/${mk}.jsonl"
  python scripts/judge_hear.py --target "data/mitigation/${mk}.jsonl" \
    --out data/mitigation/hear.jsonl
done
```

Score HEAR receptiveness on the HEAR rewrites:

```bash
python scripts/judge_hear.py --target data/mitigation/hear_1p.jsonl \
  --out data/mitigation/hear.jsonl
```

Compile mitigation and frontier tables:

```bash
python scripts/compile_mitigation.py \
  --softness data/mitigation/softness.jsonl --hear data/mitigation/hear.jsonl \
  --out data/mitigation/transform.csv

python scripts/compile_frontier.py --gens data/mitigation/gens.jsonl \
  --hear data/mitigation/hear.jsonl --out data/mitigation/frontier.csv
```

System-prompt HEAR arm (same posts, no rewrite): `gen_aita.py --system hear`.

### OEQ robustness (optional)

Rescore shipped OEQ Human / GPT-5 texts with this repo's judges (see `data/robustness/README.md`):

```bash
python scripts/export_elephant_pairs.py \
  --csv data/robustness/oeq/OEQ_full_results.csv --corpus oeq \
  --speakers human,gpt5 --out-dir data/robustness/oeq
```

### Experiment tables

Rebuild analysis CSVs from the included Qualtrics export:

```bash
python scripts/compile_experiment.py --prereg
```

### Re-plot

```bash
Rscript analysis.R
```
