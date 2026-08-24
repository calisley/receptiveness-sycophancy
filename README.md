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

   `analysis.R` loads pinned R packages via groundhog, reads the CSVs under `data/`, and needs no API keys.

**Outputs**

- Main-text figures: `plots/`
- Appendix figures: `plots/appendix/`
- Human-study robustness table: `tables/exp_human_robustness.{csv,tex}`
- Other reported statistics: printed to the console

To regenerate only the robustness table: `Rscript scripts/run_exp_robustness_table.R`

**Optional:** At the very end, `analysis.R` compares our HEAR rubric to `politeness::receptiveness()`, which needs spaCy. All figures and main statistics run without it; only that one comparison is skipped. To include it, run once **interactively in R** (not `Rscript -e` — it may need to download Miniconda and prompt for confirmation):

```r
spacyr::spacy_install()
```

Then rerun `analysis.R`. The download is about 1–2 GB and can take several minutes.

## Optional: regenerate LLM outputs

Requires **Python 3.12+**, a virtual environment, and API keys. LLM outputs will not match the paper cell-for-cell.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

(On macOS/Linux, use `.venv/bin/pip` instead.)

Scripts under `scripts/` generate replies, run judges, and compile CSVs. Prompts are defined in the Python source (`src/`). See script `--help` for usage.
