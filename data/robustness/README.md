# Robustness checks

Appendix corpora outside the main AITA figures.

- [`oeq/`](oeq/) — official ELEPHANT **OEQ** Human + GPT-5 texts rescored with this repo's USER-pin ELEPHANT + HEAR (+ positivity).

## ELEPHANT OEQ

### Layout

```
data/robustness/
  README.md
  oeq/
    OEQ.csv, OEQ_full_results.csv
    human.jsonl, gpt5.jsonl
    elephant.jsonl, hear.jsonl, positivity.jsonl
    oeq_long.csv
```

### Rebuild pairs

```bash
.venv/bin/python scripts/export_elephant_pairs.py \
  --csv data/robustness/oeq/OEQ_full_results.csv --corpus oeq \
  --speakers human,gpt5 --out-dir data/robustness/oeq
```

### Judges (resume-safe)

```bash
.venv/bin/python scripts/judge_elephant.py --target data/robustness/oeq/human.jsonl \
  --out data/robustness/oeq/elephant.jsonl
.venv/bin/python scripts/judge_hear.py --target data/robustness/oeq/gpt5.jsonl \
  --out data/robustness/oeq/hear.jsonl
# …likewise for human; positivity:
.venv/bin/python scripts/judge_positivity.py \
  --a data/robustness/oeq/human.jsonl \
  --b data/robustness/oeq/gpt5.jsonl \
  --out data/robustness/oeq/positivity.jsonl \
  --bracket "advice given to someone seeking help"
```

### Long CSV

Columns: `row_idx, source, speaker, validation, indirectness, framing, positivity, rec_raw`.

```bash
.venv/bin/python scripts/compile_robustness.py \
  --pairs-dir data/robustness/oeq \
  --elephant data/robustness/oeq/elephant.jsonl \
  --hear data/robustness/oeq/hear.jsonl \
  --positivity data/robustness/oeq/positivity.jsonl \
  --out data/robustness/oeq/oeq_long.csv
```

### Coverage

- OEQ pairs: Human 3026, GPT-5 3027 (attic row `1905` has blank Human).
- OEQ long: 6052 rows (3026×2); drops GPT-5 `1905` (no Human for positivity join).
- Judge: `gpt-5.6-luna`.
