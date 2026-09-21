#!/usr/bin/env python3
"""Build pair jsonl from AITA gens (crowd-YTA ∩ model-1p-YTA sample) plus human top comments.

  python scripts/compile/export_pairs.py --gens data/gens/terra.jsonl --source terra \\
      --speaker "GPT-5.6 Terra" --out-model data/gens/terra.jsonl \\
      --out-human data/gens/human.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lib import append_jsonl, load_aita, load_jsonl, log  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gens", required=True, type=Path)
    p.add_argument("--source", required=True)
    p.add_argument("--speaker", required=True)
    p.add_argument("--out-model", required=True, type=Path)
    p.add_argument("--out-human", type=Path, default=None)
    p.add_argument("--keep-verdict", default="YTA")
    p.add_argument(
        "--all-verdicts",
        action="store_true",
        help="Export every ok row regardless of verdict (mitigation / smoke).",
    )
    p.add_argument("--verdict-field", default="verdict_1p")
    p.add_argument("--response-field", default="response_1p")
    p.add_argument("--only-model", default=None, help="Keep gens rows with this model key.")
    p.add_argument("--merge", action="store_true")
    return p.parse_args()


def existing_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {json.loads(l)["id"] for l in path.open(encoding="utf-8") if l.strip()}


def main() -> None:
    args = parse_args()
    aita = {r["row_idx"]: r for r in load_aita()}
    keep = "" if args.all_verdicts else str(args.keep_verdict or "").upper()
    seen_m = existing_ids(args.out_model) if args.merge else set()
    seen_h = existing_ids(args.out_human) if args.merge and args.out_human else set()
    n_m = n_h = 0
    skip: dict[str, int] = {
        "not_ok": 0,
        "only_model": 0,
        "verdict": 0,
        "no_response": 0,
        "no_post": 0,
        "already_seen": 0,
    }
    verdict_counts: dict[str, int] = {}
    for rec in load_jsonl(args.gens):
        if not rec.get("ok", True):
            skip["not_ok"] += 1
            continue
        if args.only_model and str(rec.get("model") or rec.get("source") or "") != args.only_model:
            skip["only_model"] += 1
            continue
        rid = int(rec["row_idx"])
        verdict = str(rec.get(args.verdict_field) or "").upper()
        verdict_counts[verdict or "(missing)"] = verdict_counts.get(verdict or "(missing)", 0) + 1
        if keep and verdict != keep:
            skip["verdict"] += 1
            continue
        text = rec.get(args.response_field) or rec.get("response")
        if not text:
            skip["no_response"] += 1
            continue
        post = aita.get(rid)
        if not post:
            skip["no_post"] += 1
            continue
        pid = f"aita:{rid}|{args.source}"
        if pid in seen_m:
            skip["already_seen"] += 1
        if pid not in seen_m:
            append_jsonl(
                args.out_model,
                {
                    "id": pid,
                    "join_id": str(rid),
                    "row_idx": rid,
                    "corpus": "aita",
                    "source": args.source,
                    "speaker": args.speaker,
                    "label": args.speaker,
                    "arm": "1p",
                    "verdict_1p": verdict,
                    "question": post["prompt"],
                    "response": str(text),
                },
            )
            seen_m.add(pid)
            n_m += 1
        if args.out_human:
            ht = str(post.get("top_comment") or "").strip()
            hid = f"aita:{rid}|human"
            if (
                hid not in seen_h
                and ht
                and ht.lower() not in {"[removed]", "[deleted]"}
                and len(ht) >= 15
            ):
                append_jsonl(
                    args.out_human,
                    {
                        "id": hid,
                        "join_id": str(rid),
                        "row_idx": rid,
                        "corpus": "aita",
                        "source": "human",
                        "speaker": "Human",
                        "label": args.speaker,
                        "arm": "1p",
                        "question": post["prompt"],
                        "response": ht,
                    },
                )
                seen_h.add(hid)
                n_h += 1
    log(f"[export_pairs] model +{n_m} human +{n_h}")
    if n_m == 0 and n_h == 0:
        log(
            "[export_pairs] no rows exported — skips: "
            + ", ".join(f"{k}={v}" for k, v in skip.items() if v)
            + (f"; {args.verdict_field} counts: {verdict_counts}" if verdict_counts else "")
        )
        if skip["verdict"] and verdict_counts.get("(missing)"):
            log(
                "[export_pairs] hint: gens rows lack verdict labels — "
                "re-run gen_aita.py with --judge-verdicts"
            )
        elif skip["verdict"]:
            log(
                f"[export_pairs] hint: none labeled {keep!r} on {args.verdict_field!r} "
                f"(paper dens needs crowd-YTA ∩ model-1p-YTA)"
            )


if __name__ == "__main__":
    main()
