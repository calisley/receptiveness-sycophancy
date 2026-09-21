#!/usr/bin/env python3
"""Compile per-post 1p Luna verdicts (YTA/NTA/mixed/other) for all models.

Reads per-model ``paired_1p_all.csv`` / ``verdicts.jsonl`` under ``--gens-dir``
and an optional GPT-5 verdicts jsonl. Writes ``data/aita_verdicts_1p.csv``
for analysis.R raw-rate tables.

  python scripts/compile/compile_aita_verdicts.py \\
      --gens-dir data/gens --gpt5-verdicts path/to/gpt5_verdicts.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lib import log  # noqa: E402

SPEAKERS = {
    "terra": "GPT-5.6 Terra",
    "gpt5": "GPT-5",
    "sonnet5": "Claude Sonnet 5",
    "gemini_flash": "Gemini 3.7 Flash",
    "scout": "Llama 4 Scout",
}
COLS = ["model_key", "model", "row_idx", "verdict", "mixed_subtype", "source_file"]
VALID = {"YTA", "NTA", "mixed", "other"}


def add(
    store: dict[tuple[str, int], dict],
    model_key: str,
    row_idx: int,
    verdict: str,
    mixed_subtype: str | None = None,
    *,
    source: str = "",
    overwrite: bool = False,
) -> None:
    verdict = str(verdict)
    if verdict not in VALID:
        return
    key = (model_key, int(row_idx))
    if key in store and not overwrite:
        return
    store[key] = {
        "model_key": model_key,
        "model": SPEAKERS[model_key],
        "row_idx": int(row_idx),
        "verdict": verdict,
        "mixed_subtype": mixed_subtype or "",
        "source_file": source,
    }


def load_model(store: dict, mk: str, gens: Path) -> None:
    paired = gens / mk / "paired_1p_all.csv"
    verd = gens / mk / "verdicts.jsonl"
    if paired.is_file():
        df = pd.read_csv(paired)
        for r in df.itertuples(index=False):
            add(store, mk, r.row_idx, r.verdict_1p, source=paired.name, overwrite=True)
    if verd.is_file():
        for line in verd.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("arm") not in (None, "1p"):
                continue
            add(
                store,
                mk,
                r["row_idx"],
                r["verdict"],
                r.get("mixed_subtype"),
                source=verd.name,
                overwrite=False,
            )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--gens-dir",
        type=Path,
        default=ROOT / "data" / "gens",
        help="Directory with per-model subdirs containing paired_1p_all.csv / verdicts.jsonl.",
    )
    p.add_argument(
        "--gpt5-verdicts",
        type=Path,
        default=None,
        help="Optional GPT-5 1p verdicts jsonl (row_idx, verdict, mixed_subtype).",
    )
    p.add_argument("--out", type=Path, default=ROOT / "data/aita_verdicts_1p.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    store: dict[tuple[str, int], dict] = {}
    for mk in ("terra", "gemini_flash", "sonnet5", "scout", "gpt5"):
        load_model(store, mk, args.gens_dir)

    if args.gpt5_verdicts is not None:
        if not args.gpt5_verdicts.is_file():
            raise SystemExit(f"missing GPT-5 verdicts: {args.gpt5_verdicts}")
        for line in args.gpt5_verdicts.open(encoding="utf-8"):
            r = json.loads(line)
            add(
                store,
                "gpt5",
                r["row_idx"],
                r["verdict"],
                r.get("mixed_subtype"),
                source=args.gpt5_verdicts.name,
            )

    if not store:
        raise SystemExit(
            f"no verdicts found under {args.gens_dir} "
            f"(and no --gpt5-verdicts); shipped table is data/aita_verdicts_1p.csv"
        )

    rows = sorted(store.values(), key=lambda r: (r["model"], r["row_idx"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    log(f"[compile_aita_verdicts] wrote {len(rows)} rows → {args.out}")
    for mk, label in SPEAKERS.items():
        sub = [r for r in rows if r["model_key"] == mk]
        n = len(sub)
        if n == 0:
            continue
        c = Counter(r["verdict"] for r in sub)
        yta = c.get("YTA", 0)
        log(
            f"  {label}: n_judged={n} YTA={yta} "
            f"({yta / n:.1%} of judged; {yta / 2000:.1%} of 2000) "
            f"NTA={c.get('NTA', 0) / n:.1%} mixed={c.get('mixed', 0) / n:.1%} "
            f"other={c.get('other', 0) / n:.1%}"
        )


if __name__ == "__main__":
    main()
