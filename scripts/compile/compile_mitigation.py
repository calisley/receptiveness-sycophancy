#!/usr/bin/env python3
"""Compile post-level mitigation rows for R (landing + receptiveness).

Writes a long CSV: one row per (model, post, arm). Softness votes are reduced
to a plurality landing here; T, SEs, and mean receptiveness are computed in R.

  python scripts/compile/compile_mitigation.py \\
      --softness data/mitigation/softness.jsonl \\
      --hear data/mitigation/hear.jsonl \\
      --out data/mitigation/transform.csv

Optional prompt arm (HEAR system prompt vs unprompted 3p):

  python scripts/compile/compile_mitigation.py \\
      --softness data/mitigation/softness.jsonl \\
      --hear data/mitigation/hear.jsonl \\
      --prompt-softness data/mitigation/prompt_softness.jsonl \\
      --prompt-hear data/mitigation/prompt_hear.jsonl \\
      --out data/mitigation/transform.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lib import MODELS, load_jsonl, log  # noqa: E402

# Softness pair → analysis arm, and which HEAR cond scores the 1p side.
PAIR_ARM = {
    "base_1p_vs_3p": ("free", "base"),
    "hear_1p_vs_3p": ("tool", "hear"),
    "hear_1p_vs_unprompted_3p": ("prompt", "hear"),
}

COLS = ["model_key", "model", "id", "row_idx", "arm", "landing", "rec_raw"]
ROW_RE = re.compile(r"(?:aita_yta|aita):(\d+)")


def plurality(rows: list[dict]) -> str | None:
    """Plurality landing; adjudicator 'other' counts as a tie (same)."""
    c = Counter(r.get("landing") for r in rows if r.get("ok", True))
    if not c:
        return None
    top = max(c.values())
    winners = [k for k, v in c.items() if v == top]
    if len(winners) != 1:
        return None
    win = winners[0]
    if win == "other":
        return "same"
    if win in ("1p_softer", "3p_softer", "same"):
        return win
    return None


def row_idx(pid: str) -> int | None:
    m = ROW_RE.search(pid)
    return int(m.group(1)) if m else None


def label_for(mk: str) -> str:
    return MODELS.get(mk, {}).get("speaker") or mk


def hear_lookup(rows: list[dict]) -> dict[tuple[str, str, str], float]:
    """(model, id, cond) → rec_raw. Also accept id keys that embed model."""
    out: dict[tuple[str, str, str], float] = {}
    for r in rows:
        if r.get("rec_raw") is None:
            continue
        mk = str(r.get("model") or "")
        pid = str(r.get("id") or r.get("key") or "")
        cond = str(r.get("cond") or r.get("arm") or "base")
        if cond in ("1p", "base_1p"):
            cond = "base"
        if cond in ("hear_1p", "hear_sys", "sys"):
            cond = "hear"
        if not mk or not pid:
            continue
        out[(mk, pid, cond)] = float(r["rec_raw"])
        # rewrite export ids: aita:{rid}|{model}|hear
        if "|hear" in pid or pid.endswith("|hear"):
            base_id = pid.split("|")[0]
            out[(mk, base_id, "hear")] = float(r["rec_raw"])
        elif "|" in pid:
            base_id = pid.split("|")[0]
            out.setdefault((mk, base_id, cond), float(r["rec_raw"]))
    return out


def rec_for(
    hear: dict[tuple[str, str, str], float],
    mk: str,
    pid: str,
    cond: str,
    *,
    fallback_base: bool = False,
) -> float | None:
    rid = row_idx(pid)
    cands = [pid]
    if rid is not None:
        cands.extend(
            [
                f"aita_yta:{rid}",
                f"aita:{rid}",
                f"aita:{rid}|{mk}",
                f"aita_yta:{rid}|{mk}",
                f"aita:{rid}|{mk}|hear",
            ]
        )
    conds = [cond]
    if fallback_base and cond != "base":
        conds.append("base")
    for c in conds:
        for cand in cands:
            if (mk, cand, c) in hear:
                return hear[(mk, cand, c)]
    return None


def arm_rows(
    votes: list[dict],
    hear: dict[tuple[str, str, str], float],
    pair: str,
    arm: str,
    cond: str,
) -> list[dict]:
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for v in votes:
        if v.get("pair") != pair:
            continue
        mk = str(v.get("model") or "")
        pid = str(v.get("id") or "")
        if mk and pid:
            by[(mk, pid)].append(v)
    # Prefer the post universe from votes; hang posts with no decisive landing.
    out = []
    for (mk, pid), rows in sorted(by.items()):
        land = plurality(rows)
        out.append(
            {
                "model_key": mk,
                "model": label_for(mk),
                "id": pid,
                "row_idx": row_idx(pid) if row_idx(pid) is not None else "",
                "arm": arm,
                "landing": land if land is not None else "",
                # Prompt-run HEAR files often tag the prompted 1p as cond=base.
                "rec_raw": rec_for(
                    hear, mk, pid, cond, fallback_base=(arm == "prompt")
                ),
            }
        )
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--softness", required=True, type=Path, help="base/tool softness votes")
    p.add_argument("--hear", required=True, type=Path, help="HEAR scores for free/tool 1p")
    p.add_argument("--prompt-softness", type=Path, default=None)
    p.add_argument("--prompt-hear", type=Path, default=None)
    p.add_argument("--out", type=Path, default=ROOT / "data/mitigation/transform.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    votes = load_jsonl(args.softness)
    hear = hear_lookup(load_jsonl(args.hear))
    rows: list[dict] = []
    for pair, (arm, cond) in PAIR_ARM.items():
        if arm == "prompt":
            continue
        rows.extend(arm_rows(votes, hear, pair, arm, cond))
    if args.prompt_softness:
        p_votes = load_jsonl(args.prompt_softness)
        p_hear = hear_lookup(load_jsonl(args.prompt_hear)) if args.prompt_hear else hear
        # Accept either explicit pair or missing pair (legacy prompt compare).
        for v in p_votes:
            v.setdefault("pair", "hear_1p_vs_unprompted_3p")
        rows.extend(
            arm_rows(p_votes, p_hear, "hear_1p_vs_unprompted_3p", "prompt", "hear")
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in COLS})
    arms = Counter(r["arm"] for r in rows)
    models = sorted({r["model_key"] for r in rows})
    log(f"[compile_mitigation] wrote {len(rows)} rows → {args.out} arms={dict(arms)} models={models}")


if __name__ == "__main__":
    main()
