#!/usr/bin/env python3
"""Clean Qualtrics Advice-responses export into R-ready CSVs.

Reads the raw Qualtrics CSV (3 header rows), drops experimenter self-tests,
reshapes to one row per (participant × item), and maps A/B labels onto
base/rewrite.

Default (no flags): Aug 14 20-item pilot. Fixed A/B from data/experiment/qa.json;
writes data/experiment/advice_responses_clean_*.csv (does not touch prereg outputs).

--prereg: Aug 18 100-item wave. Per-participant ord_<id>, provenance from
items.json; writes data/experiment/responses.csv (+ participants.csv).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "experiment" / "Advice responses_August 14, 2026_07.08.csv"
QA = ROOT / "data" / "experiment" / "qa.json"
QN = ROOT / "data" / "experiment" / "questions.json"
OUT_LONG = ROOT / "data" / "experiment" / "responses_pilot.csv"
OUT_PART = ROOT / "data" / "experiment" / "participants_pilot.csv"
OUT_NOTES = ROOT / "data" / "experiment" / "cleaning_notes_pilot.md"

PREREG_RAW = ROOT / "data" / "experiment" / "Advice responses prereg_August 18, 2026_20.46.csv"
PREREG_ITEMS = ROOT / "data" / "experiment" / "items.json"
PREREG_WAVE = "prereg_20260818"

SELF_IP = ""  # redacted in public deposit; drop rule is a no-op
# Experimenter / QC Prolific IDs redacted in the public deposit. Released
# analysis tables are already compiled; flag_qc_review is baked into CSVs.
EXPERIMENTER_PIDS: set[str] = set()
QC_REVIEW_PIDS: set[str] = set()
CONSENT_YES = "I consent to participate"

VERDICT_MAP = {
    "Definitely not in the wrong": 1,
    "Probably not in the wrong": 2,
    "Unsure": 3,
    "Probably in the wrong": 4,
    "Definitely in the wrong": 5,
}
QUALITY_MAP = {
    "Very bad": 1,
    "Bad": 2,
    "Somewhat bad": 3,
    "Neither good nor bad": 4,
    "Somewhat good": 5,
    "Good": 6,
    "Very good": 7,
}
# -2 = strong A … 0 = equal/none … +2 = strong B
LISTEN_MAP = {
    "Definitely Response A": -2,
    "Probably Response A": -1,
    "About equally likely to listen to both": 0,
    "Probably Response B": 1,
    "Definitely Response B": 2,
}
ADVICE_MAP = {
    "Definitely commenter A": -2,
    "Probably commenter A": -1,
    "No preference": 0,
    "Probably commenter B": 1,
    "Definitely commenter B": 2,
}

LONG_CORE_COLS = [
    "response_id",
    "prolific_pid",
    "start_date",
    "end_date",
    "recorded_date",
    "duration_sec",
    "progress",
    "finished",
    "consent",
    "outro_paraphrase",
    "item_id",
    "order_ab",
    "source_A",
    "source_B",
    "verdict_label",
    "verdict",
    "quality_A_label",
    "quality_B_label",
    "quality_A",
    "quality_B",
    "quality_human",
    "quality_rewrite",
    "quality_rewrite_minus_human",
    "listen_label",
    "listen_A_to_B",
    "listen_pref_rewrite",
    "listen_chose_human",
    "listen_chose_rewrite",
    "advice_label",
    "advice_A_to_B",
    "advice_pref_rewrite",
    "advice_chose_human",
    "advice_chose_rewrite",
    "t_v_first_click",
    "t_v_last_click",
    "t_v_page_submit",
    "t_v_click_count",
    "t_r_first_click",
    "t_r_last_click",
    "t_r_page_submit",
    "t_r_click_count",
    "flag_fast_verdict_page",
    "flag_fast_response_page",
]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _scalar_num(val) -> float:
    return pd.to_numeric(val, errors="coerce")


def _cell(row: pd.Series, *names: str):
    for n in names:
        if n in row.index:
            val = row[n]
            if pd.notna(val) and str(val).strip() != "":
                return val
    return pd.NA


def _is_blank(val) -> bool:
    return pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan"


def _chose(score, order, want: str):
    """score is −2..+2 (neg=A, pos=B). want is 'human' (base) or 'rewrite'."""
    if pd.isna(score) or order not in ("ab", "ba"):
        return pd.NA
    if score == 0:
        return 0
    chose_a = score < 0
    is_base = (order == "ab" and chose_a) or (order == "ba" and not chose_a)
    is_rewrite = not is_base
    return int(is_base if want == "human" else is_rewrite)


def _unknown_labels(long: pd.DataFrame) -> list[str]:
    out: list[str] = []
    for col, mapping, label in [
        ("verdict_label", VERDICT_MAP, "verdict"),
        ("quality_A_label", QUALITY_MAP, "quality_A"),
        ("quality_B_label", QUALITY_MAP, "quality_B"),
        ("listen_label", LISTEN_MAP, "listen"),
        ("advice_label", ADVICE_MAP, "advice"),
    ]:
        unknown = sorted(
            {str(x) for x in long[col].dropna().unique() if str(x) not in mapping}
        )
        if unknown:
            out.append(f"Unrecognized {label} labels: {unknown}")
    return out


# ---------------------------------------------------------------------------
# Pilot (default): fixed A/B from qa.json — do not change output names/schema
# ---------------------------------------------------------------------------


def run_pilot(csv_path: Path, qa_path: Path, out_dir: Path) -> None:
    out_long = out_dir / "advice_responses_clean_long.csv"
    out_part = out_dir / "advice_responses_clean_participants.csv"
    out_notes = out_dir / "advice_responses_CLEANING_NOTES.md"

    if not csv_path.exists():
        raise SystemExit(f"missing {csv_path}")

    qa = json.loads(qa_path.read_text())
    item_meta = {int(it["id"]): it for it in qa["items"]}

    raw = pd.read_csv(csv_path, skiprows=[1, 2], dtype=str)
    n_raw = len(raw)

    difficulties: list[str] = []

    status_vals = sorted(set(raw["Status"].dropna().astype(str)))
    if status_vals == ["IP Address"] or "IP Address" in status_vals:
        difficulties.append(
            f"`Status` column is corrupted in this export (unique values: {status_vals}). "
            "Not used. All rows have Finished=True / Progress=100, so we treat them as completes."
        )

    n_self = int((raw["IPAddress"] == SELF_IP).sum())
    df = raw[raw["IPAddress"] != SELF_IP].copy()
    if n_self == 0:
        difficulties.append(f"No rows found with self IP {SELF_IP} (already removed?).")

    if "PROLIFIC_PID" not in df.columns:
        difficulties.append("No `PROLIFIC_PID` column — cannot link to Prolific payments.")
        df["PROLIFIC_PID"] = pd.NA
    n_pid = df["PROLIFIC_PID"].nunique(dropna=True)
    if n_pid != len(df):
        difficulties.append(
            f"PROLIFIC_PID not unique after drop: {n_pid} unique vs {len(df)} rows."
        )

    rows: list[dict] = []
    v_cols = [c for c in df.columns if re.fullmatch(r"v_\d+", c)]
    for _, r in df.iterrows():
        answered = [c for c in v_cols if pd.notna(r[c]) and str(r[c]).strip() != ""]
        if len(answered) != 5:
            difficulties.append(
                f"Response {r.get('ResponseId')}: expected 5 items, found {len(answered)} "
                f"({answered})."
            )

        for vc in answered:
            item_id = int(vc.split("_", 1)[1])
            meta = item_meta.get(item_id)
            if meta is None:
                difficulties.append(f"Item id {item_id} missing from qa.json — skipped mapping.")
                order = None
                src_a = src_b = None
                tag_suffix = None
            else:
                order = meta["order"]
                src_a, src_b = meta["A"], meta["B"]
                tag_suffix = f"{item_id}_{order}"

            def get(*names: str):
                for n in names:
                    if n in df.columns:
                        val = r[n]
                        if pd.notna(val) and str(val).strip() != "":
                            return val
                return pd.NA

            gA = get(f"gA_{tag_suffix}") if tag_suffix else pd.NA
            gB = get(f"gB_{tag_suffix}") if tag_suffix else pd.NA
            listen = get(f"l_{tag_suffix}") if tag_suffix else pd.NA
            advice = get(f"a_{tag_suffix}") if tag_suffix else pd.NA
            verdict = r[vc]

            qA = QUALITY_MAP.get(str(gA), pd.NA)
            qB = QUALITY_MAP.get(str(gB), pd.NA)
            if order == "ab":
                q_human, q_rewrite = qA, qB
            elif order == "ba":
                q_human, q_rewrite = qB, qA
            else:
                q_human = q_rewrite = pd.NA

            listen_n = LISTEN_MAP.get(str(listen), pd.NA)
            advice_n = ADVICE_MAP.get(str(advice), pd.NA)

            if pd.isna(listen_n) or order is None:
                listen_pref_rewrite = pd.NA
            else:
                listen_pref_rewrite = listen_n if order == "ab" else -listen_n
            if pd.isna(advice_n) or order is None:
                advice_pref_rewrite = pd.NA
            else:
                advice_pref_rewrite = advice_n if order == "ab" else -advice_n

            rows.append(
                {
                    "response_id": r["ResponseId"],
                    "prolific_pid": r.get("PROLIFIC_PID"),
                    "start_date": r.get("StartDate"),
                    "end_date": r.get("EndDate"),
                    "recorded_date": r.get("RecordedDate"),
                    "duration_sec": _num(pd.Series([r.get("Duration (in seconds)")])).iloc[0],
                    "progress": r.get("Progress"),
                    "finished": r.get("Finished"),
                    "consent": r.get("consent"),
                    "outro_paraphrase": r.get("outro_paraphrase"),
                    "item_id": item_id,
                    "order_ab": order,
                    "source_A": src_a,
                    "source_B": src_b,
                    "verdict_label": verdict,
                    "verdict": VERDICT_MAP.get(str(verdict), pd.NA),
                    "quality_A_label": gA,
                    "quality_B_label": gB,
                    "quality_A": qA,
                    "quality_B": qB,
                    "quality_human": q_human,
                    "quality_rewrite": q_rewrite,
                    "quality_rewrite_minus_human": (
                        q_rewrite - q_human
                        if pd.notna(q_rewrite) and pd.notna(q_human)
                        else pd.NA
                    ),
                    "listen_label": listen,
                    "listen_A_to_B": listen_n,
                    "listen_pref_rewrite": listen_pref_rewrite,
                    "listen_chose_human": _chose(listen_n, order, "human"),
                    "listen_chose_rewrite": _chose(listen_n, order, "rewrite"),
                    "advice_label": advice,
                    "advice_A_to_B": advice_n,
                    "advice_pref_rewrite": advice_pref_rewrite,
                    "advice_chose_human": _chose(advice_n, order, "human"),
                    "advice_chose_rewrite": _chose(advice_n, order, "rewrite"),
                    "t_v_first_click": _num(pd.Series([get(f"t_v_{item_id}_First Click")])).iloc[0],
                    "t_v_last_click": _num(pd.Series([get(f"t_v_{item_id}_Last Click")])).iloc[0],
                    "t_v_page_submit": _num(pd.Series([get(f"t_v_{item_id}_Page Submit")])).iloc[0],
                    "t_v_click_count": _num(pd.Series([get(f"t_v_{item_id}_Click Count")])).iloc[0],
                    "t_r_first_click": _num(pd.Series([get(f"t_r_{item_id}_First Click")])).iloc[0],
                    "t_r_last_click": _num(pd.Series([get(f"t_r_{item_id}_Last Click")])).iloc[0],
                    "t_r_page_submit": _num(pd.Series([get(f"t_r_{item_id}_Page Submit")])).iloc[0],
                    "t_r_click_count": _num(pd.Series([get(f"t_r_{item_id}_Click Count")])).iloc[0],
                }
            )

    long = pd.DataFrame(rows)
    long["listen_chose_human"] = [
        _chose(s, o, "human") for s, o in zip(long["listen_A_to_B"], long["order_ab"])
    ]
    long["listen_chose_rewrite"] = [
        _chose(s, o, "rewrite") for s, o in zip(long["listen_A_to_B"], long["order_ab"])
    ]
    long["advice_chose_human"] = [
        _chose(s, o, "human") for s, o in zip(long["advice_A_to_B"], long["order_ab"])
    ]
    long["advice_chose_rewrite"] = [
        _chose(s, o, "rewrite") for s, o in zip(long["advice_A_to_B"], long["order_ab"])
    ]

    long["flag_fast_verdict_page"] = (long["t_v_page_submit"] < 3).astype("Int64")
    long["flag_fast_response_page"] = (long["t_r_page_submit"] < 5).astype("Int64")

    part = (
        long.groupby(["response_id", "prolific_pid"], dropna=False)
        .agg(
            start_date=("start_date", "first"),
            end_date=("end_date", "first"),
            recorded_date=("recorded_date", "first"),
            duration_sec=("duration_sec", "first"),
            n_items=("item_id", "count"),
            mean_t_v_page_submit=("t_v_page_submit", "mean"),
            mean_t_r_page_submit=("t_r_page_submit", "mean"),
            n_fast_verdict_pages=("flag_fast_verdict_page", "sum"),
            n_fast_response_pages=("flag_fast_response_page", "sum"),
            outro_paraphrase=("outro_paraphrase", "first"),
        )
        .reset_index()
    )
    part["flag_short_duration"] = (part["duration_sec"] < 300).astype("Int64")
    part["flag_any_fast_page"] = (
        (part["n_fast_verdict_pages"] > 0) | (part["n_fast_response_pages"] > 0)
    ).astype("Int64")

    for col in ["verdict", "quality_A", "quality_B", "listen_A_to_B", "advice_A_to_B"]:
        n_miss = int(long[col].isna().sum())
        if n_miss:
            difficulties.append(f"Long file: {n_miss} missing values in `{col}`.")

    difficulties.extend(_unknown_labels(long))

    coverage = long["item_id"].value_counts().sort_index()
    if coverage.min() < 5:
        difficulties.append(
            f"Uneven item coverage (min n={int(coverage.min())}, max n={int(coverage.max())}). "
            "Block randomizer with EvenPresentation usually balances; small N can still wobble."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    long.to_csv(out_long, index=False)
    part.to_csv(out_part, index=False)

    notes = f"""# Advice responses — cleaning notes

**Source:** `{csv_path.name}`  
**Dropped self IP:** `{SELF_IP}` ({n_self} rows)  
**Kept participants:** {len(df)} (from {n_raw} raw)  
**Long rows:** {len(long)} (= participants × 5 items)  

## Outputs
- `{out_long.name}` — analysis table (one row per participant × item)
- `{out_part.name}` — participant-level summary + speeder heuristics

## Coding
| Variable | Scale |
|---|---|
| `verdict` | 1=Definitely not in the wrong … 5=Definitely in the wrong |
| `quality_*` | 1=Very bad … 7=Very good |
| `listen_A_to_B` / `advice_A_to_B` | −2=strong A … 0=tie … +2=strong B (screen labels) |
| `listen_pref_rewrite` / `advice_pref_rewrite` | same −2…+2 but **+ = prefer rewrite**, − = prefer human (order-corrected) |
| `quality_human` / `quality_rewrite` | quality scores mapped off A/B using fixed `order_ab` |
| `quality_rewrite_minus_human` | rewrite − human (positive ⇒ rewrite rated better) |

**A/B assignment is fixed per item** (from `qa.json`), not re-randomized per participant. Item selection (5 of 20) is random.

## Speeder heuristics (not automatic exclusions)
- `flag_fast_verdict_page`: verdict page submit < 3s
- `flag_fast_response_page`: responses page submit < 5s
- `flag_short_duration`: total survey < 300s

Review these before dropping anyone.

## Difficulties / caveats
"""
    if difficulties:
        notes += "\n".join(f"- {d}" for d in difficulties) + "\n"
    else:
        notes += "- None beyond the usual Qualtrics triple-header.\n"

    notes += """
## Privacy
Clean files **omit IP addresses** and lat/long. Participant IDs in released
tables are anonymous `participant_id` values; Prolific IDs are blanked.
"""
    out_notes.write_text(notes)

    print(f"wrote {out_long} ({len(long)} rows)")
    print(f"wrote {out_part} ({len(part)} rows)")
    print(f"wrote {out_notes}")
    print("difficulties:")
    for d in difficulties:
        print(" -", d)
    print("item coverage:\n", coverage.to_string())
    print("duration_sec:", part["duration_sec"].describe().to_string())
    print(
        "fast pages: verdict",
        int(long["flag_fast_verdict_page"].sum()),
        "response",
        int(long["flag_fast_response_page"].sum()),
        "; short duration participants",
        int(part["flag_short_duration"].sum()),
    )


# ---------------------------------------------------------------------------
# Prereg 100-item wave: per-participant ord_<id> + response provenance
# ---------------------------------------------------------------------------


def _item_order(row: pd.Series, item_id: int) -> str | None:
    raw_ord = str(_cell(row, f"ord_{item_id}", "ord") or "").strip().lower()
    if raw_ord in ("ab", "ba"):
        return raw_ord
    for cand in ("ab", "ba"):
        if not _is_blank(_cell(row, f"l_{item_id}_{cand}", f"gA_{item_id}_{cand}")):
            return cand
    return None


def _is_preview(row: pd.Series) -> bool:
    return str(row.get("Status") or "") == "Survey Preview" or str(
        row.get("DistributionChannel") or ""
    ).lower() == "preview"


def _drop_reason(row: pd.Series, n_shown: int) -> str | None:
    if _is_preview(row):
        return "survey_preview"
    ip = str(row.get("IPAddress") or "").strip()
    if ip == SELF_IP:
        return "self_test_ip"
    pid = row.get("PROLIFIC_PID")
    pid_s = None if _is_blank(pid) else str(pid).strip()
    if pid_s in EXPERIMENTER_PIDS:
        return "experimenter_pid"
    if pid_s is None:
        return "missing_pid"
    if str(row.get("consent") or "").strip() != CONSENT_YES:
        return "non_consent"
    if n_shown == 0:
        return "no_items"
    return None


def run_prereg(
    csv_path: Path,
    items_path: Path,
    out_dir: Path,
    wave: str,
) -> None:
    out_long = out_dir / "responses.csv"
    out_part = out_dir / "participants.csv"
    out_notes = out_dir / "cleaning_notes.md"

    if not csv_path.exists():
        raise SystemExit(f"missing {csv_path}")
    if not items_path.exists():
        raise SystemExit(f"missing {items_path}")

    items = json.loads(items_path.read_text())
    item_meta = {int(it["id"]): it for it in items}

    raw = pd.read_csv(csv_path, skiprows=[1, 2], dtype=str)
    n_raw = len(raw)
    v_cols = [c for c in raw.columns if re.fullmatch(r"v_\d+", c)]
    difficulties: list[str] = []

    status_vals = sorted(set(raw["Status"].dropna().astype(str)))
    difficulties.append(
        f"`Status` is unusable as a complete/incomplete flag (unique values: {status_vals}). "
        "All rows have Finished=True / Progress=100. Survey Preview / missing PID / "
        "experimenter-PID rows are dropped from the released CSVs."
    )

    n_self = int((raw.get("IPAddress", pd.Series(dtype=str)) == SELF_IP).sum())
    if n_self == 0:
        difficulties.append(
            f"No rows with experimenter self IP {SELF_IP} (none dropped on that rule)."
        )

    if "PROLIFIC_PID" not in raw.columns:
        difficulties.append("No `PROLIFIC_PID` column — cannot link to Prolific payments.")
        raw["PROLIFIC_PID"] = pd.NA

    raw = raw.copy()
    raw["_n_shown"] = [
        sum(1 for c in v_cols if not _is_blank(r[c])) for _, r in raw.iterrows()
    ]
    raw["_recorded_dt"] = pd.to_datetime(raw["RecordedDate"], errors="coerce")
    raw["_drop_reason"] = [
        _drop_reason(r, int(r["_n_shown"])) for _, r in raw.iterrows()
    ]

    # Duplicate PIDs: among rows not already dropped, keep latest RecordedDate.
    eligible = raw["_drop_reason"].isna() & ~raw["PROLIFIC_PID"].map(_is_blank)
    pid_counts = raw.loc[eligible, "PROLIFIC_PID"].value_counts()
    dup_pids = set(pid_counts[pid_counts > 1].index.astype(str))
    keep_latest: dict[str, str] = {}
    if dup_pids:
        sub = raw.loc[eligible & raw["PROLIFIC_PID"].isin(dup_pids)].sort_values(
            "_recorded_dt", kind="mergesort"
        )
        keep_latest = (
            sub.groupby("PROLIFIC_PID", sort=False)["ResponseId"].last().to_dict()
        )
        extra = 0
        for i, r in raw.iterrows():
            pid = str(r.get("PROLIFIC_PID") or "")
            if pid not in dup_pids or not pd.isna(r["_drop_reason"]):
                continue
            if r["ResponseId"] != keep_latest[pid]:
                raw.at[i, "_drop_reason"] = "duplicate_pid_not_latest"
                extra += 1
        difficulties.append(
            f"Duplicate PROLIFIC_PID: {n_raw} raw rows, "
            f"{int(raw['PROLIFIC_PID'].nunique(dropna=True))} unique non-missing PIDs, "
            f"{int(raw['PROLIFIC_PID'].map(_is_blank).sum())} missing PID. "
            f"PIDs with >1 eligible completion: {sorted(dup_pids)}. "
            f"Rule: keep latest RecordedDate ({extra} earlier attempt(s) dropped). "
            "Kept duplicate-PID rows are flagged `flag_duplicate_pid`."
        )

    raw["keep"] = raw["_drop_reason"].isna().astype(int)
    n_keep = int(raw["keep"].sum())
    drop_counts = raw["_drop_reason"].value_counts(dropna=True).to_dict()

    q145_nonempty = 0
    if "Q145" in raw.columns:
        q145_nonempty = int((~raw["Q145"].map(_is_blank)).sum())
        difficulties.append(
            f"`Q145` (typed Prolific ID) is nonempty in {q145_nonempty}/{n_raw} rows; "
            "URL embedded data `PROLIFIC_PID` is the analysis ID. Typed IDs are stored "
            "on the participant file as `typed_prolific_id` and are not used to fill "
            "missing PIDs."
        )

    # Long rows for every shown item (including later-dropped responses, so
    # participant aggregates can still report n_items). Analysis long = keep==1.
    long_rows: list[dict] = []
    n_missing_order = 0
    n_unknown_item = 0
    expected_items = 5

    for _, r in raw.iterrows():
        answered = [c for c in v_cols if not _is_blank(r[c])]
        n_ans = len(answered)
        if n_ans not in (0, expected_items) and pd.isna(r["_drop_reason"]):
            difficulties.append(
                f"Response {r.get('ResponseId')}: expected {expected_items} items, "
                f"found {n_ans}."
            )

        pid = r.get("PROLIFIC_PID")
        pid_s = None if _is_blank(pid) else str(pid).strip()
        is_preview = str(r.get("Status") or "") == "Survey Preview" or str(
            r.get("DistributionChannel") or ""
        ).lower() == "preview"
        flag_dup = int(bool(pid_s) and pid_s in dup_pids)
        flag_miss_pid = int(pid_s is None)
        flag_qc = int(bool(pid_s) and pid_s in QC_REVIEW_PIDS)

        for vc in answered:
            item_id = int(vc.split("_", 1)[1])
            meta = item_meta.get(item_id)
            if meta is None:
                n_unknown_item += 1
                origin = model = model_label = title = pd.NA
                dz = rec_z_base = rec_z_rewrite = pd.NA
            else:
                origin = meta.get("origin")
                model = meta.get("model")
                model_label = meta.get("model_label")
                if origin == "human":
                    model = pd.NA
                    model_label = pd.NA
                dz = meta.get("dz")
                rec_z_base = meta.get("rec_z_base")
                rec_z_rewrite = meta.get("rec_z_rewrite")
                title = meta.get("title")

            order = _item_order(r, item_id)
            if order is None:
                n_missing_order += 1
                src_a = src_b = pd.NA
            elif order == "ab":
                src_a, src_b = "base", "rewrite"
            else:
                src_a, src_b = "rewrite", "base"

            gA = _cell(r, f"gA_{item_id}", f"gA_{item_id}_{order}" if order else "")
            gB = _cell(r, f"gB_{item_id}", f"gB_{item_id}_{order}" if order else "")
            listen = _cell(r, f"l_{item_id}", f"l_{item_id}_{order}" if order else "")
            advice = _cell(r, f"a_{item_id}", f"a_{item_id}_{order}" if order else "")
            verdict = r[vc]

            qA = QUALITY_MAP.get(str(gA), pd.NA) if not _is_blank(gA) else pd.NA
            qB = QUALITY_MAP.get(str(gB), pd.NA) if not _is_blank(gB) else pd.NA
            if order == "ab":
                q_base, q_rewrite = qA, qB
            elif order == "ba":
                q_base, q_rewrite = qB, qA
            else:
                q_base = q_rewrite = pd.NA

            listen_n = LISTEN_MAP.get(str(listen), pd.NA) if not _is_blank(listen) else pd.NA
            advice_n = ADVICE_MAP.get(str(advice), pd.NA) if not _is_blank(advice) else pd.NA
            if pd.isna(listen_n) or order is None:
                listen_pref_rewrite = pd.NA
            else:
                listen_pref_rewrite = listen_n if order == "ab" else -listen_n
            if pd.isna(advice_n) or order is None:
                advice_pref_rewrite = pd.NA
            else:
                advice_pref_rewrite = advice_n if order == "ab" else -advice_n

            rec_zb = pd.to_numeric(rec_z_base, errors="coerce")
            rec_zr = pd.to_numeric(rec_z_rewrite, errors="coerce")
            if pd.notna(rec_zb) and pd.notna(rec_zr):
                rewrite_more_positive = int(rec_zr > rec_zb)
                positivity_cat = (
                    "Rewrite more positive" if rewrite_more_positive else "Rewrite not more positive"
                )
            else:
                rewrite_more_positive = pd.NA
                positivity_cat = pd.NA

            long_rows.append(
                {
                    "response_id": r["ResponseId"],
                    "prolific_pid": pid_s,
                    "start_date": r.get("StartDate"),
                    "end_date": r.get("EndDate"),
                    "recorded_date": r.get("RecordedDate"),
                    "duration_sec": _scalar_num(r.get("Duration (in seconds)")),
                    "progress": r.get("Progress"),
                    "finished": r.get("Finished"),
                    "consent": r.get("consent"),
                    "outro_paraphrase": r.get("outro_paraphrase"),
                    "item_id": item_id,
                    "order_ab": order,
                    "source_A": src_a,
                    "source_B": src_b,
                    "verdict_label": verdict,
                    "verdict": VERDICT_MAP.get(str(verdict), pd.NA)
                    if not _is_blank(verdict)
                    else pd.NA,
                    "quality_A_label": gA,
                    "quality_B_label": gB,
                    "quality_A": qA,
                    "quality_B": qB,
                    # Legacy names: "human" here means the *base* comment (human- or model-origin).
                    "quality_human": q_base,
                    "quality_rewrite": q_rewrite,
                    "quality_rewrite_minus_human": (
                        q_rewrite - q_base
                        if pd.notna(q_rewrite) and pd.notna(q_base)
                        else pd.NA
                    ),
                    "listen_label": listen,
                    "listen_A_to_B": listen_n,
                    "listen_pref_rewrite": listen_pref_rewrite,
                    "listen_chose_human": _chose(listen_n, order, "human"),
                    "listen_chose_rewrite": _chose(listen_n, order, "rewrite"),
                    "advice_label": advice,
                    "advice_A_to_B": advice_n,
                    "advice_pref_rewrite": advice_pref_rewrite,
                    "advice_chose_human": _chose(advice_n, order, "human"),
                    "advice_chose_rewrite": _chose(advice_n, order, "rewrite"),
                    "t_v_first_click": _scalar_num(
                        _cell(r, f"t_v_{item_id}_First Click")
                    ),
                    "t_v_last_click": _scalar_num(
                        _cell(r, f"t_v_{item_id}_Last Click")
                    ),
                    "t_v_page_submit": _scalar_num(
                        _cell(r, f"t_v_{item_id}_Page Submit")
                    ),
                    "t_v_click_count": _scalar_num(
                        _cell(r, f"t_v_{item_id}_Click Count")
                    ),
                    "t_r_first_click": _scalar_num(
                        _cell(r, f"t_r_{item_id}_First Click")
                    ),
                    "t_r_last_click": _scalar_num(
                        _cell(r, f"t_r_{item_id}_Last Click")
                    ),
                    "t_r_page_submit": _scalar_num(
                        _cell(r, f"t_r_{item_id}_Page Submit")
                    ),
                    "t_r_click_count": _scalar_num(
                        _cell(r, f"t_r_{item_id}_Click Count")
                    ),
                    "survey_wave": wave,
                    "source_file": csv_path.name,
                    "origin": origin,
                    "model": model if not _is_blank(model) else pd.NA,
                    "model_label": model_label if not _is_blank(model_label) else pd.NA,
                    "dz": dz,
                    "rec_z_base": rec_zb,
                    "rec_z_rewrite": rec_zr,
                    "rec_z_human": rec_zb,
                    "rec_delta": (
                        rec_zr - rec_zb if pd.notna(rec_zr) and pd.notna(rec_zb) else pd.NA
                    ),
                    "title": title,
                    "rewrite_more_positive": rewrite_more_positive,
                    "positivity_cat": positivity_cat,
                    "positivity": rewrite_more_positive,
                    "flag_duplicate_pid": flag_dup,
                    "flag_missing_pid": flag_miss_pid,
                    "flag_survey_preview": int(is_preview),
                    "flag_qc_review": flag_qc,
                    "_keep": int(r["keep"]),
                }
            )

    if n_unknown_item:
        difficulties.append(f"{n_unknown_item} long rows had item_id missing from {items_path.name}.")
    if n_missing_order:
        difficulties.append(
            f"{n_missing_order} long rows missing per-participant `ord_<id>` (could not flip A/B)."
        )

    long_all = pd.DataFrame(long_rows)
    long_all["flag_fast_verdict_page"] = (long_all["t_v_page_submit"] < 3).astype("Int64")
    long_all["flag_fast_response_page"] = (long_all["t_r_page_submit"] < 5).astype("Int64")

    long = long_all.loc[long_all["_keep"] == 1].drop(columns=["_keep"]).reset_index(drop=True)

    # Participant file: released completes only (drops stay in CLEANING_NOTES).
    part_rows: list[dict] = []
    long_by_rid = long_all.groupby("response_id", dropna=False)
    for _, r in raw.iterrows():
        if int(r["keep"]) != 1:
            continue
        rid = r["ResponseId"]
        pid = r.get("PROLIFIC_PID")
        pid_s = None if _is_blank(pid) else str(pid).strip()
        if rid in long_by_rid.groups:
            g = long_by_rid.get_group(rid)
            n_items = int(len(g))
            mean_tv = float(g["t_v_page_submit"].mean()) if n_items else pd.NA
            mean_tr = float(g["t_r_page_submit"].mean()) if n_items else pd.NA
            n_fast_v = int(g["flag_fast_verdict_page"].fillna(0).sum())
            n_fast_r = int(g["flag_fast_response_page"].fillna(0).sum())
            n_human = int((g["origin"] == "human").sum())
            n_model = int((g["origin"] == "model").sum())
        else:
            n_items = 0
            mean_tv = mean_tr = pd.NA
            n_fast_v = n_fast_r = 0
            n_human = n_model = 0
        duration = _scalar_num(r.get("Duration (in seconds)"))
        part_rows.append(
            {
                "response_id": rid,
                "prolific_pid": pid_s,
                "typed_prolific_id": None
                if "Q145" not in raw.columns or _is_blank(r.get("Q145"))
                else str(r.get("Q145")).strip(),
                "start_date": r.get("StartDate"),
                "end_date": r.get("EndDate"),
                "recorded_date": r.get("RecordedDate"),
                "duration_sec": duration,
                "progress": r.get("Progress"),
                "finished": r.get("Finished"),
                "consent": r.get("consent"),
                "n_items": n_items,
                "n_human_origin": n_human,
                "n_model_origin": n_model,
                "mean_t_v_page_submit": mean_tv,
                "mean_t_r_page_submit": mean_tr,
                "n_fast_verdict_pages": n_fast_v,
                "n_fast_response_pages": n_fast_r,
                "outro_paraphrase": r.get("outro_paraphrase"),
                "flag_short_duration": pd.NA
                if pd.isna(duration)
                else int(duration < 300),
                "flag_any_fast_page": int((n_fast_v > 0) or (n_fast_r > 0)),
                "flag_duplicate_pid": int(bool(pid_s) and pid_s in dup_pids),
                "flag_qc_review": int(bool(pid_s) and pid_s in QC_REVIEW_PIDS),
            }
        )

    part = pd.DataFrame(part_rows)
    kept_part = part

    difficulties.extend(_unknown_labels(long))
    for col in ["verdict", "quality_A", "quality_B", "listen_A_to_B", "advice_A_to_B", "order_ab", "origin"]:
        n_miss = int(long[col].isna().sum())
        if n_miss:
            difficulties.append(f"Long file (kept): {n_miss} missing values in `{col}`.")
    miss_resp = long[
        long["quality_A"].isna()
        | long["quality_B"].isna()
        | long["listen_A_to_B"].isna()
        | long["advice_A_to_B"].isna()
    ]
    if len(miss_resp):
        bits = [
            f"{r.response_id} item {int(r.item_id)}"
            + (" (survey preview)" if int(r.flag_survey_preview) else "")
            for r in miss_resp.itertuples()
        ]
        difficulties.append(
            "Incomplete response-page ratings (verdict present, gA/gB/listen/advice blank): "
            + "; ".join(bits)
            + "."
        )

    coverage = long["item_id"].value_counts().sort_index()
    origin_counts = long["origin"].value_counts(dropna=False).to_dict()
    model_counts = (
        long.loc[long["origin"] == "model", "model_label"]
        .value_counts(dropna=False)
        .to_dict()
    )
    n_qc = int(kept_part["flag_qc_review"].sum())
    difficulties.append(
        f"QC-review PIDs kept in analysis files with `flag_qc_review=1` "
        f"(n_participants={n_qc}, n_long_rows="
        f"{int(long['flag_qc_review'].sum())}): {sorted(QC_REVIEW_PIDS)}. "
        "Not auto-dropped."
    )

    # Column order
    extra_long = [
        "survey_wave",
        "source_file",
        "origin",
        "model",
        "model_label",
        "dz",
        "rec_z_base",
        "rec_z_rewrite",
        "rec_z_human",
        "rec_delta",
        "title",
        "rewrite_more_positive",
        "positivity_cat",
        "positivity",
        "flag_duplicate_pid",
        "flag_qc_review",
    ]
    long = long[LONG_CORE_COLS + extra_long]

    out_dir.mkdir(parents=True, exist_ok=True)
    long.to_csv(out_long, index=False)
    part.to_csv(out_part, index=False)

    drop_lines = (
        "\n".join(f"- `{k}`: {v}" for k, v in sorted(drop_counts.items()))
        if drop_counts
        else "- (none)"
    )
    unknown = [d for d in difficulties if d.startswith("Unrecognized")]
    unknown_txt = "; ".join(unknown) if unknown else "none"

    notes = f"""# Advice responses (prereg) — cleaning notes

**Source:** `{csv_path.name}`  
**Wave:** `{wave}`  
**Item bank:** `{items_path.name}` ({len(item_meta)} items)  
**Raw rows:** {n_raw}  
**Unique `PROLIFIC_PID` (non-missing):** {int(raw['PROLIFIC_PID'].nunique(dropna=True))}  
**Released participants:** {n_keep}  
**Long rows (released, participant × item shown):** {len(long)}  

Do **not** confuse with the Aug 14 20-item pilot (`responses_pilot.csv`).

## Outputs
- `{out_long.name}` — analysis table (one row per released participant × item shown)
- `{out_part.name}` — one row per released participant (tester / preview / missing-PID rows omitted)
- `{out_notes.name}` — this file (records who was dropped; those people are **not** in the CSVs)

## Mechanical drops (omitted from both CSVs)
Dropped, in order: Qualtrics Survey Preview; experimenter self-test IP `{SELF_IP}`; known experimenter Prolific PID(s) `{sorted(EXPERIMENTER_PIDS)}`; missing `PROLIFIC_PID`; non-consent; empty / no-items; then duplicate `PROLIFIC_PID` (keep **latest `RecordedDate`**).

{drop_lines}

Self-IP rows dropped: {n_self}.

**Not dropped:** QC-review PIDs `{sorted(QC_REVIEW_PIDS)}` (flagged `flag_qc_review`); short duration; fast pages. Those stay in the analysis files with flags.

## Duplicate PID rule
Raw export has {n_raw} rows vs {int(raw['PROLIFIC_PID'].nunique(dropna=True))} unique non-missing PIDs ({int(raw['PROLIFIC_PID'].map(_is_blank).sum())} missing PID). Duplicate eligible PIDs after experimenter/preview/missing-PID drops: `{sorted(dup_pids) if dup_pids else []}`. Earlier consented attempts of a remaining duplicate PID are omitted (`duplicate_pid_not_latest`).

## Response provenance
These tag the **base comment** (the human Reddit top comment or the model's own 1p), not which side of the A/B screen it appeared on.

| Column | Meaning |
|---|---|
| `survey_wave` | `{wave}` |
| `source_file` | raw CSV filename |
| `origin` | `human` or `model` from the item bank |
| `model` / `model_label` | model identity; NA for human-origin items |
| `dz`, `rec_z_base`, `rec_z_rewrite`, `title` | from `{items_path.name}` |
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
min n={int(coverage.min()) if len(coverage) else 0}, max n={int(coverage.max()) if len(coverage) else 0}, n_items_shown={int(coverage.size)} of {len(item_meta)} in bank.

## Origin split (kept long rows)
{origin_counts}

Model-origin `model_label` counts: {model_counts}

## Unrecognized labels
{unknown_txt}

## Difficulties / caveats
"""
    if difficulties:
        notes += "\n".join(f"- {d}" for d in difficulties) + "\n"
    else:
        notes += "- None beyond the usual Qualtrics triple-header.\n"

    notes += """
## Privacy
Clean files **omit IP addresses** and lat/long. Participant IDs in released
tables are anonymous `participant_id` values; Prolific IDs are blanked.
"""
    out_notes.write_text(notes)

    miss = {
        c: int(long[c].isna().sum())
        for c in [
            "verdict",
            "quality_A",
            "quality_B",
            "listen_A_to_B",
            "advice_A_to_B",
            "order_ab",
            "origin",
            "model",
        ]
    }

    print(f"wrote {out_long} ({len(long)} rows)")
    print(f"wrote {out_part} ({len(part)} rows)")
    print(f"wrote {out_notes}")
    print("n participants kept:", n_keep)
    print("n long rows:", len(long))
    print(
        "item coverage min/max:",
        int(coverage.min()) if len(coverage) else None,
        int(coverage.max()) if len(coverage) else None,
        f"({int(coverage.size)} items)",
    )
    print("origin split (long rows):", origin_counts)
    print("model_label (model-origin):", model_counts)
    print("duration_sec (kept):")
    print(kept_part["duration_sec"].describe().to_string())
    print("missingness (kept long):", miss)
    print("unrecognized labels:", unknown_txt)
    print("drop_reason counts:", drop_counts)
    print("duplicate PID handling:", sorted(dup_pids), "keep_latest", keep_latest)
    print(
        "fast pages (kept): verdict",
        int(long["flag_fast_verdict_page"].sum()),
        "response",
        int(long["flag_fast_response_page"].sum()),
        "; short duration kept participants",
        int(kept_part["flag_short_duration"].fillna(0).sum()),
    )
    print("flag_qc_review kept participants:", n_qc)
    print("difficulties:")
    for d in difficulties:
        print(" -", d)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Clean Qualtrics Advice-responses export into R-ready CSVs."
    )
    p.add_argument("--csv", type=Path, default=None, help="Raw Qualtrics CSV (3 header rows).")
    p.add_argument(
        "--items",
        type=Path,
        default=None,
        help="Item bank JSON (prereg: data/experiment/items.json).",
    )
    p.add_argument("--qa", type=Path, default=None, help="qa.json for the Aug 14 pilot only.")
    p.add_argument("--out-dir", type=Path, default=ROOT / "data" / "experiment")
    p.add_argument("--wave", default=None, help="survey_wave tag (prereg default: prereg_20260818).")
    p.add_argument(
        "--prereg",
        action="store_true",
        help="100-item prereg wave: randomized ord_<id>, provenance columns, prereg output names.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    prereg = bool(args.prereg)
    if args.csv is not None and "prereg" in args.csv.name.lower():
        prereg = True
    if args.items is not None and "prereg" in args.items.name.lower():
        prereg = True

    if prereg:
        run_prereg(
            csv_path=args.csv or PREREG_RAW,
            items_path=args.items or PREREG_ITEMS,
            out_dir=args.out_dir,
            wave=args.wave or PREREG_WAVE,
        )
        return

    run_pilot(
        csv_path=args.csv or RAW,
        qa_path=args.qa or QA,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
