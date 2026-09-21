#!/usr/bin/env python3
"""Join 1p/3p gens + HEAR into frontier.csv.

  python scripts/compile/compile_frontier.py --gens data/mitigation/gens.jsonl \\
      --hear data/mitigation/hear.jsonl --out data/mitigation/frontier.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lib import MODELS, load_jsonl, log  # noqa: E402

COLS = ["model", "row_idx", "rec_raw", "verdict_1p", "verdict_3p"]


def hear_map(path: Path) -> dict[str, float]:
    out = {}
    for r in load_jsonl(path):
        pid = str(r.get("id") or r.get("key") or "")
        if pid and r.get("rec_raw") is not None:
            out[pid] = float(r["rec_raw"])
    return out


def rec_for(g: dict, hear: dict[str, float]) -> float | None:
    mk = str(g.get("model") or "")
    rid = g.get("row_idx")
    pid = str(g.get("id") or "")
    for cand in (
        f"aita:{rid}|{mk}",
        pid,
        f"{pid}|{mk}",
        f"aita_yta:{rid}|{mk}",
    ):
        if cand in hear:
            return hear[cand]
    if g.get("rec_raw") is not None:
        return float(g["rec_raw"])
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gens", required=True, type=Path)
    p.add_argument("--hear", required=True, type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "data/mitigation/frontier.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    hear = hear_map(args.hear)
    rows = []
    for g in load_jsonl(args.gens):
        if not g.get("ok", True):
            continue
        rec = rec_for(g, hear)
        if rec is None or g.get("verdict_1p") is None or g.get("verdict_3p") is None:
            continue
        mk = str(g.get("model") or "")
        label = MODELS.get(mk, {}).get("speaker") or g.get("speaker") or mk
        rows.append(
            {
                "model": label,
                "row_idx": int(g["row_idx"]),
                "rec_raw": rec,
                "verdict_1p": g["verdict_1p"],
                "verdict_3p": g["verdict_3p"],
            }
        )
    out = pd.DataFrame(rows)[COLS]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    log(f"[compile_frontier] wrote {len(out)} rows → {args.out}")


if __name__ == "__main__":
    main()
