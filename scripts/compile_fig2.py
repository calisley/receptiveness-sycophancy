#!/usr/bin/env python3
"""Join human vs rewrite scores into receptiveness_transform.csv.

  python scripts/compile_fig2.py --human ... --rewrite ... \\
      --out data/receptiveness_transform.csv
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lib import load_jsonl, load_pairs, log, pairwise_dummy  # noqa: E402

COLS = [
    "row_idx",
    "model",
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
        if pid and met in {"validation", "indirectness", "framing"} and r.get("label") in (0, 1, 0.0, 1.0, "0", "1"):
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


def compile_rows(
    humans: list[dict],
    rewrites: dict[str, dict],
    ele: dict[str, dict[str, int]],
    hear: dict[str, float],
    pos: dict[tuple[str, str, str], float],
    *,
    model: str,
) -> list[dict]:
    rows = []
    for h in humans:
        jid = str(h["join_id"])
        rw = rewrites.get(jid)
        if not rw:
            continue
        for speaker, src, rec in (("Human", "human", h), ("Rewrite", "rewrite", rw)):
            labels = ele.get(rec["id"], {})
            rec_raw = hear.get(rec["id"])
            other = "rewrite" if src == "human" else "human"
            dummy = pos.get((jid, src, other))
            if rec_raw is None or dummy is None or not {"validation", "indirectness", "framing"} <= labels.keys():
                continue
            rows.append(
                {
                    "row_idx": int(rec["row_idx"]),
                    "model": model,
                    "source": src,
                    "speaker": speaker,
                    "validation": labels["validation"],
                    "indirectness": labels["indirectness"],
                    "framing": labels["framing"],
                    "positivity": pairwise_dummy(dummy),
                    "rec_raw": rec_raw,
                }
            )
    return rows


def merge_elephant_maps(*paths: Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for path in paths:
        if path and path.is_file():
            for pid, labels in elephant_map(path).items():
                out[pid].update(labels)
    return dict(out)


def merge_hear_maps(*paths: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for path in paths:
        if path and path.is_file():
            out.update(hear_map(path))
    return out


def human_scores_from_csv(path: Path) -> tuple[dict[str, dict[str, int]], dict[str, float]]:
    """Load human baseline scores keyed by pair id (aita:{row_idx}|human)."""
    if not path.is_file():
        return {}, {}
    ele: dict[str, dict[str, int]] = {}
    hear: dict[str, float] = {}
    df = pd.read_csv(path)
    h = df[df["source"] == "human"]
    for _, r in h.iterrows():
        pid = f"aita:{int(r['row_idx'])}|human"
        ele[pid] = {
            "validation": int(r["validation"]),
            "indirectness": int(r["indirectness"]),
            "framing": int(r["framing"]),
        }
        hear[pid] = float(r["rec_raw"])
    return ele, hear


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--human", type=Path, required=True)
    p.add_argument("--rewrite", type=Path, required=True)
    p.add_argument("--elephant", type=Path, required=True)
    p.add_argument("--positivity", type=Path, required=True)
    p.add_argument("--hear", type=Path, required=True)
    p.add_argument("--model", default="GPT-5.6 Terra", help="Rewriter / dens label.")
    p.add_argument("--out", type=Path, default=ROOT / "data/receptiveness_transform.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ele = elephant_map(args.elephant)
    pos = positivity_map(args.positivity)
    hear = hear_map(args.hear)
    humans = load_pairs(args.human)
    rewrites = {str(p["join_id"]): p for p in load_pairs(args.rewrite)}
    rows = compile_rows(humans, rewrites, ele, hear, pos, model=args.model)
    out = pd.DataFrame(rows)[COLS]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    log(f"[compile_fig2] wrote {len(out)} rows → {args.out}")


if __name__ == "__main__":
    main()
