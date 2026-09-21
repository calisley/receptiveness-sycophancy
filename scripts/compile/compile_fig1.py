#!/usr/bin/env python3
"""Join pairs + ELEPHANT + positivity + HEAR into aita_sycophancy_scores.csv.

Each model panel is crowd-YTA ∩ that model's 1p=YTA. Human rows are the top
comment on the same posts.

  python scripts/compile/compile_fig1.py --pairs-dir data/gens/aita \\
      --out data/aita_sycophancy_scores.csv
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
    "corpus",
    "panel",
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
        if not pid or met not in {"validation", "indirectness", "framing"}:
            continue
        if r.get("label") not in (0, 1, 0.0, 1.0, "0", "1"):
            continue
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
    p.add_argument("--positivity", type=Path, required=True)
    p.add_argument("--hear", type=Path, required=True)
    p.add_argument("--human-pairs", type=Path, default=None)
    p.add_argument("--out", type=Path, default=ROOT / "data/aita_sycophancy_scores.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ele = elephant_map(args.elephant)
    pos = positivity_map(args.positivity)
    hear = hear_map(args.hear)
    human_path = args.human_pairs or (args.pairs_dir / "human.jsonl")
    humans = {str(p["join_id"]): p for p in load_pairs(human_path)} if human_path.is_file() else {}
    skip = {
        "human.jsonl",
        "elephant.jsonl",
        "hear.jsonl",
        "positivity.jsonl",
        "gens.jsonl",
        "rewrites.jsonl",
        "pos_fig2.jsonl",
    }
    rows = []
    for path in sorted(args.pairs_dir.glob("*.jsonl")):
        if path.name in skip or "gens" in path.name:
            continue
        models = load_pairs(path)
        if not models:
            continue
        src = str(models[0].get("source") or path.stem)
        speaker = str(models[0].get("speaker") or src)
        n_ok = 0
        for m in models:
            labels = ele.get(m["id"], {})
            rec = hear.get(m["id"])
            if rec is None or not {"validation", "indirectness", "framing"} <= labels.keys():
                continue
            jid = str(m["join_id"])
            dummy = pos.get((jid, src, "human"))
            if dummy is None:
                continue
            rows.append(
                {
                    "row_idx": int(m["row_idx"]),
                    "corpus": "aita",
                    "panel": speaker,
                    "source": src,
                    "speaker": speaker,
                    "validation": labels["validation"],
                    "indirectness": labels["indirectness"],
                    "framing": labels["framing"],
                    "positivity": pairwise_dummy(dummy),
                    "rec_raw": rec,
                }
            )
            h = humans.get(jid)
            if h:
                hl = ele.get(h["id"], {})
                hrec = hear.get(h["id"])
                hd = pos.get((jid, "human", src))
                if (
                    hrec is not None
                    and {"validation", "indirectness", "framing"} <= hl.keys()
                    and hd is not None
                ):
                    rows.append(
                        {
                            "row_idx": int(h["row_idx"]),
                            "corpus": "aita",
                            "panel": speaker,
                            "source": "human",
                            "speaker": "Human",
                            "validation": hl["validation"],
                            "indirectness": hl["indirectness"],
                            "framing": hl["framing"],
                            "positivity": pairwise_dummy(hd),
                            "rec_raw": hrec,
                        }
                    )
            n_ok += 1
        log(f"[compile_fig1] {speaker}: kept {n_ok}/{len(models)}")
    out = pd.DataFrame(rows)[COLS]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    log(f"[compile_fig1] wrote {len(out)} rows → {args.out}")


if __name__ == "__main__":
    main()
