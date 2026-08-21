# Advice responses (prereg) — cleaning notes

**Source:** `Advice responses prereg_August 18, 2026_20.46.csv`  
**Wave:** `prereg_20260818`  
**Item bank:** `items.json` (100 items)  
**Raw rows:** 206  
**Unique `PROLIFIC_PID` (non-missing):** 201  
**Released participants:** 200  
**Long rows (released, participant × item shown):** 1000  

Do **not** confuse with the Aug 14 20-item pilot (`advice_responses_clean_long.csv`).

## Outputs
- `responses.csv` — analysis table (one row per released participant × item shown)
- `participants.csv` — one row per released participant (tester / preview / missing-PID rows omitted)
- `cleaning_notes.md` — this file (records who was dropped; those people are **not** in the CSVs)

## Mechanical drops (omitted from both CSVs)
Dropped, in order: Qualtrics Survey Preview; experimenter self-test IP `66.31.164.127`; known experimenter Prolific PID(s) `['6a7e8f75cfcd04db97e588b6']`; missing `PROLIFIC_PID`; non-consent; empty / no-items; then duplicate `PROLIFIC_PID` (keep **latest `RecordedDate`**).

- `experimenter_pid`: 4
- `missing_pid`: 1
- `survey_preview`: 1

Self-IP rows dropped: 0.

**Not dropped:** QC-review PIDs `['608981c1be83df6a5452398e', '69694a17e34d205d4484f00a']` (flagged `flag_qc_review`); short duration; fast pages. Those stay in the analysis files with flags.

## Duplicate PID rule
Raw export has 206 rows vs 201 unique non-missing PIDs (2 missing PID). Duplicate eligible PIDs after experimenter/preview/missing-PID drops: `[]`. Earlier consented attempts of a remaining duplicate PID are omitted (`duplicate_pid_not_latest`).

## Response provenance
These tag the **base comment** (the human Reddit top comment or the model's own 1p), not which side of the A/B screen it appeared on.

| Column | Meaning |
|---|---|
| `survey_wave` | `prereg_20260818` |
| `source_file` | raw CSV filename |
| `origin` | `human` or `model` from the item bank |
| `model` / `model_label` | model identity; NA for human-origin items |
| `dz`, `rec_z_base`, `rec_z_rewrite`, `title` | from `items.json` |
| `rec_z_human` | alias of `rec_z_base` (legacy name for R) |
| `rec_delta` | `rec_z_rewrite - rec_z_base` |
| `source_A` / `source_B` | `base` or `rewrite` using **this participant's** `ord_<id>` |
| `quality_human` / `listen_chose_human` / … | **legacy names**: "human" means the **base** comment, which may be model-origin. Use `origin` to split human-origin vs model-origin. |

`qa_prereg.json` is **not** used as a fixed ab/ba map (`order` is `"randomized"`). Flip listen/advice so `*_pref_rewrite` is + = prefer rewrite using `ord_<id>`: `ab` ⇒ base is Response A / rewrite is B; `ba` ⇒ flipped.

## Coding
| Variable | Scale |
|---|---|
| `verdict` | 1=Definitely not in the wrong … 5=Definitely in the wrong |
| `quality_*` | 1=Very bad … 7=Very good |
| `listen_A_to_B` / `advice_A_to_B` | −2=strong A … 0=tie … +2=strong B (screen labels) |
| `listen_pref_rewrite` / `advice_pref_rewrite` | same −2…+2 but **+ = prefer rewrite**, − = prefer base (order-corrected) |
| `quality_rewrite_minus_human` | rewrite − base (positive ⇒ rewrite rated better) |
| `rewrite_more_positive` | 1 iff `rec_z_rewrite > rec_z_base` (no new Sharma scoring) |
| `positivity` | same 0/1 as `rewrite_more_positive` |
| `positivity_cat` | `Rewrite more positive` / `Rewrite not more positive` |

Likert maps match the Aug 14 pilot cleaner. Export is **choice text**, not integer recodes.

## Speeder / QC flags (not automatic exclusions)
- `flag_fast_verdict_page`: verdict page submit < 3s
- `flag_fast_response_page`: responses page submit < 5s
- `flag_short_duration`: total survey < 300s
- `flag_any_fast_page`: any fast verdict or response page
- `flag_duplicate_pid`, `flag_qc_review`

## Item coverage (kept)
min n=8, max n=11, n_items_shown=100 of 100 in bank.

## Origin split (kept long rows)
{'model': 502, 'human': 498}

Model-origin `model_label` counts: {'Gemini 3.7 Flash': 217, 'Claude Sonnet 5': 196, 'GPT-5': 59, 'GPT-5.6 Terra': 20, 'Llama 4 Scout': 10}

## Unrecognized labels
none

## Difficulties / caveats
- `Status` is unusable as a complete/incomplete flag (unique values: ['IP Address', 'Survey Preview']). All rows have Finished=True / Progress=100. Survey Preview / missing PID / experimenter-PID rows are dropped from the released CSVs.
- No rows with experimenter self IP 66.31.164.127 (none dropped on that rule).
- `Q145` (typed Prolific ID) is nonempty in 1/206 rows; URL embedded data `PROLIFIC_PID` is the analysis ID. Typed IDs are stored on the participant file as `typed_prolific_id` and are not used to fill missing PIDs.
- QC-review PIDs kept in analysis files with `flag_qc_review=1` (n_participants=2, n_long_rows=10): ['608981c1be83df6a5452398e', '69694a17e34d205d4484f00a']. Not auto-dropped.

## Privacy
Clean files **omit IP addresses** and lat/long. `prolific_pid` is retained for payment/QC; strip before public deposit.
