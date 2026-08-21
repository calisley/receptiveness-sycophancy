#!/usr/bin/env python3
"""Export Human / GPT-5 pair jsonl from ELEPHANT OEQ full_results CSV.

  python scripts/export_elephant_pairs.py \\
      --csv data/robustness/oeq/OEQ_full_results.csv \\
      --corpus oeq --speakers human,gpt5 \\
      --out-dir data/robustness/oeq
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lib import log  # noqa: E402

SPEAKER_MAP = {
    "human": ("Human", "human", "Human"),
    "gpt5": ("GPT-5", "gpt5", "GPT-5"),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", required=True, type=Path)
    p.add_argument("--corpus", required=True, choices=("oeq",))
    p.add_argument(
        "--speakers",
        default="human,gpt5",
        help="Comma-separated: human and/or gpt5 (column names Human / GPT-5).",
    )
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--stratified", type=int, default=None, help="Keep every k-th row (after valid filter).")
    return p.parse_args()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.csv)
    if "Unnamed: 0" in df.columns:
        df = df.rename(columns={"Unnamed: 0": "row_idx"})
    elif "row_idx" not in df.columns:
        df = df.reset_index(names="row_idx")
    df["row_idx"] = df["row_idx"].astype(int)

    speakers = [s.strip().lower() for s in args.speakers.split(",") if s.strip()]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for key in speakers:
        if key not in SPEAKER_MAP:
            raise SystemExit(f"unknown speaker {key!r}; choose from {list(SPEAKER_MAP)}")
        col, source, speaker = SPEAKER_MAP[key]
        if col not in df.columns:
            raise SystemExit(f"missing column {col!r} in {args.csv}")
        rows: list[dict] = []
        for rec in df.to_dict("records"):
            q = str(rec.get("prompt") or rec.get("question") or "").strip()
            a = str(rec.get(col) or "").strip()
            if not q or not a or a.lower() in {"nan", "none"}:
                continue
            rid = int(rec["row_idx"])
            rows.append(
                {
                    "id": f"{args.corpus}:{rid}|{source}",
                    "join_id": str(rid),
                    "row_idx": rid,
                    "corpus": args.corpus,
                    "source": source,
                    "speaker": speaker,
                    "question": q,
                    "response": a,
                }
            )
        if args.stratified:
            rows = rows[:: args.stratified]
        if args.limit is not None:
            rows = rows[: args.limit]
        out = args.out_dir / f"{source}.jsonl"
        write_jsonl(out, rows)
        log(f"[export_elephant] {key} n={len(rows)} → {out}")


if __name__ == "__main__":
    main()
