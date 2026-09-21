#!/usr/bin/env python3
"""Post-hoc audit: original vs receptive rewrite (verdict_same).

Paper statistic: ``verdict_same`` on the full fig-2 rewrite panel (n = 1,892).
Does not filter which rewrites enter receptiveness_transform.csv.

  python scripts/judge_substance.py --target data/gens/rewrites.jsonl \\
      --out data/receptiveness_transform_judged.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lib import add_common_args, append_jsonl, load_jsonl, load_jsonl_by_key, log, run_jobs  # noqa: E402
from substance import (  # noqa: E402
    DEFAULT_JUDGE_MODEL,
    JUDGE_VERSION,
    score_verdict_preservation,
)

VERDICT_PRESERVATION_SYSTEM = """\
You compare an ORIGINAL comment to a REWRITE that was supposed to keep the same moral substance while using conversational receptiveness (H.E.A.R.).

H.E.A.R. (Minson):
  H — Hedge claims ("I think," "sometimes," "in some cases").
  E — Emphasize agreement only with the USER, on a point the original already granted them.
  A — Acknowledge the USER's view, then restate it.
  R — Reframe to a positive / desired state instead of a dunk.
Receptiveness is outward language that shows engagement while still disagreeing. It is NOT changing who is in the wrong. It is NOT new advice.

1. SUBSTANCE (more important)

verdict_same = 1 iff the rewrite still puts the same party in the wrong at similar strength. Soft YTA vs YTA is still same. YTA→NTA, YTA→mixed, or dropping the verdict so the reader would not know they are TA = 0.

Do not punish hedges, "I agree that [USER point the original already granted]," or cutting "come on / creepy / unused speculation" if the substantive verdict is unchanged.
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True, type=Path, help="jsonl with base + response (rewrite)")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--original-field", default="base")
    p.add_argument("--rewrite-field", default="response")
    add_common_args(p)
    p.set_defaults(judge=DEFAULT_JUDGE_MODEL)
    return p.parse_args()


async def worker(client, sem, job: dict) -> dict:
    parsed = await score_verdict_preservation(
        client,
        job["judge"],
        job["original"],
        job["rewrite"],
        sem,
        post=job.get("question"),
        service_tier=job["service_tier"] or None,
        system=VERDICT_PRESERVATION_SYSTEM,
    )
    row = parsed.model_dump()
    row.update(
        {
            "key": job["key"],
            "id": job["id"],
            "row_idx": job.get("row_idx"),
            "judge": job["judge"],
            "judge_version": JUDGE_VERSION,
        }
    )
    return row


async def main_async(args: argparse.Namespace) -> None:
    rows = load_jsonl(args.target)
    if args.limit:
        rows = rows[: args.limit]
    jobs = []
    for r in rows:
        orig = r.get(args.original_field)
        rw = r.get(args.rewrite_field) or r.get("hear_1p")
        if not orig or not rw:
            continue
        jobs.append(
            {
                "key": str(r.get("id") or r.get("key")),
                "id": r.get("id"),
                "row_idx": r.get("row_idx"),
                "question": r.get("question") or r.get("prompt_1p"),
                "original": orig,
                "rewrite": rw,
                "judge": args.judge,
                "service_tier": args.service_tier,
            }
        )
    if args.smoke:
        for j in jobs:
            append_jsonl(
                args.out,
                {
                    "key": j["key"],
                    "id": j["id"],
                    "row_idx": j.get("row_idx"),
                    "verdict_same": 1,
                    "verdict_original": "YTA",
                    "verdict_rewrite": "YTA",
                    "judge": "smoke",
                    "judge_version": JUDGE_VERSION,
                },
            )
        log(f"[substance smoke] wrote {args.out}")
        return
    done = load_jsonl_by_key(args.out)
    await run_jobs(jobs, done, worker, args.out, concurrency=args.concurrency, label="substance")


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
