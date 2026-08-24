#!/usr/bin/env python3
"""Join robustness pair + ELEPHANT + HEAR (+ optional positivity) into long CSV.

  python scripts/compile/compile_robustness.py \\
      --pairs-dir data/robustness/oeq \\
      --elephant data/robustness/oeq/elephant.jsonl \\
      --hear data/robustness/oeq/hear.jsonl \\
      --positivity data/robustness/oeq/positivity.jsonl \\
      --out data/robustness/oeq/oeq_long.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lib import load_jsonl, load_pairs, log, pairwise_dummy  # noqa: E402

COLS = [
    "row_idx",
    "source",
    "speaker",
    "validation",
    "indirectness",
    "framing",
    "positivity",
    "rec_raw",
]


def elephant_map(path: Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for r in load_jsonl(path):
        pid = str(r.get("id") or "")
        met = str(r.get("metric") or "")
        if pid and met in {"validation", "indirectness", "framing"} and r.get("label") in (
            0,
            1,
            0.0,
            1.0,
            "0",
            "1",
        ):
            out[pid][met] = int(float(r["label"]))
    return out


def positivity_map(path: Path) -> dict[tuple[str, str, str], float]:
    wins: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for r in load_jsonl(path):
        jid = str(r.get("join_id"))
        a_src, b_src = str(r.get("a_source")), str(r.get("b_source"))
        winner = str(r.get("more_positive_source") or "")
        if not jid or not winner:
            continue
        wins[(jid, a_src, b_src)].append(int(winner == a_src))
        wins[(jid, b_src, a_src)].append(int(winner == b_src))
    return {k: float(sum(v) / len(v)) for k, v in wins.items() if v}


def hear_map(path: Path) -> dict[str, float]:
    out = {}
    for r in load_jsonl(path):
        pid = str(r.get("id") or r.get("key") or "")
        if pid and r.get("rec_raw") is not None:
            out[pid] = float(r["rec_raw"])
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs-dir", type=Path, required=True)
    p.add_argument("--elephant", type=Path, required=True)
    p.add_argument("--hear", type=Path, required=True)
    p.add_argument("--positivity", type=Path, default=None, help="Optional pairwise positivity scores.")
    p.add_argument("--out", type=Path, required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ele = elephant_map(args.elephant)
    hear = hear_map(args.hear)
    pos = positivity_map(args.positivity) if args.positivity and args.positivity.is_file() else {}
    skip_names = {
        "elephant.jsonl",
        "hear.jsonl",
        "positivity.jsonl",
        "oeq_long.csv",
    }
    rows = []
    for path in sorted(args.pairs_dir.glob("*.jsonl")):
        if path.name in skip_names or path.name.startswith("gens_"):
            continue
        pairs = load_pairs(path)
        if not pairs:
            continue
        for rec in pairs:
            labels = ele.get(rec["id"], {})
            rec_raw = hear.get(rec["id"])
            if rec_raw is None or not {"validation", "indirectness", "framing"} <= labels.keys():
                continue
            src = str(rec.get("source") or path.stem)
            speaker = str(rec.get("speaker") or src)
            jid = str(rec["join_id"])
            positivity = None
            if pos:
                # OEQ: pairwise human↔gpt5.
                other = "gpt5" if src == "human" else "human" if src == "gpt5" else None
                if not other:
                    continue
                dummy = pos.get((jid, src, other))
                if dummy is None:
                    continue
                positivity = pairwise_dummy(dummy)
            rows.append(
                {
                    "row_idx": int(rec["row_idx"]),
                    "source": src,
                    "speaker": speaker,
                    "validation": labels["validation"],
                    "indirectness": labels["indirectness"],
                    "framing": labels["framing"],
                    "positivity": positivity,
                    "rec_raw": rec_raw,
                }
            )
    out = pd.DataFrame(rows, columns=COLS)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    log(f"[compile_robustness] wrote {len(out)} rows → {args.out}")


if __name__ == "__main__":
    main()
