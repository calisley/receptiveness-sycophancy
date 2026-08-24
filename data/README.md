# Data

Analysis inputs for `Rscript analysis.R`.

| Path | Role |
|---|---|
| `aita/AITA-YTA.csv` | AITA posts + human top comments (eligibility filter) |
| `aita_verdicts_1p.csv` | Luna 1p verdicts by model |
| `aita_sycophancy_scores.csv` | Fig 1 scores; `panel` = crowd-YTA ∩ that model's 1p=YTA |
| `receptiveness_transform.csv` | Fig 2 human/rewrite score pairs |
| `receptiveness_transform_judged.jsonl` | Fig 2 verdict-preservation judgments |
| `mitigation/frontier.csv` | Fig 5 free-arm verdict rates |
| `mitigation/transform.csv` | Fig 5 free/prompt/tool receptiveness |
| `robustness/oeq/oeq_long.csv` | OEQ correlation robustness |
| `hear/hear_v5_signed_scores.jsonl` | HEAR rubric scores on Yeomans training texts |
| `hear/receptive_train.csv` | Matching training texts (for rebuild scripts) |
| `experiment/items.json` | Survey item bank |
| `experiment/responses.csv` | Human-experiment ratings |
| `experiment/participants.csv` | One row per participant |
