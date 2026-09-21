#!/usr/bin/env python3
"""Merge HEAR rewrites onto 1p/3p gens (adds hear_1p for softness).

  python scripts/compile/merge_hear.py \\
      --gens data/mitigation/gens.jsonl \\
      --rewrites data/mitigation/hear_1p.jsonl \\
      --out data/mitigation/gens_with_hear.jsonl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lib import append_jsonl, load_jsonl, log  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gens", required=True, type=Path)
    p.add_argument("--rewrites", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    return p.parse_args()


def rewrite_index(rows: list[dict]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        if not r.get("ok", True):
            continue
        text = r.get("hear_1p") or r.get("response")
        if not text:
            continue
        mk = str(r.get("model") or "").strip()
        rid = r.get("row_idx")
        src = str(r.get("source") or "")
        if not mk and "|hear" in src:
            mk = src.split("|hear", 1)[0]
        if mk.endswith("|hear"):
            mk = mk[: -len("|hear")]
        keys = []
        if rid is not None and mk:
            keys.append((str(int(rid)), mk))
        pid = str(r.get("id") or "")
        if pid:
            # aita:24|terra|hear → (24, terra)
            parts = pid.split("|")
            if len(parts) >= 2 and parts[0].startswith("aita"):
                num = parts[0].split(":")[-1]
                keys.append((num, parts[1] if parts[1] != "hear" else mk))
        for k in keys:
            if k[0] and k[1]:
                out[k] = r
    return out


def main() -> None:
    args = parse_args()
    rew = rewrite_index(load_jsonl(args.rewrites))
    n = 0
    if args.out.exists():
        args.out.unlink()
    for g in load_jsonl(args.gens):
        row = dict(g)
        mk = str(g.get("model") or "")
        rid = g.get("row_idx")
        hit = rew.get((str(int(rid)), mk)) if rid is not None and mk else None
        if hit:
            row["hear_1p"] = hit.get("hear_1p") or hit.get("response")
            n += 1
        append_jsonl(args.out, row)
    log(f"[merge_hear] merged hear_1p onto {n}/{len(load_jsonl(args.gens))} gens → {args.out}")


if __name__ == "__main__":
    main()
