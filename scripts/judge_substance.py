#!/usr/bin/env python3
"""Substance+HEAR judge on original vs rewrite pairs.

  python scripts/judge_substance.py --target data/gens/rewrites.jsonl --out data/receptiveness_transform_judged.jsonl
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
    score_receptivize_hear_substance,
)


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
    parsed = await score_receptivize_hear_substance(
        client,
        job["judge"],
        job["original"],
        job["rewrite"],
        sem,
        post=job.get("question"),
        service_tier=job["service_tier"] or None,
    )
    row = parsed.model_dump()
    row.update(
        {
            "key": job["key"],
            "id": job["id"],
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
                "key": str(r.get("id")),
                "id": r.get("id"),
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
                    "verdict_same": 1,
                    "takeaway_same": 0,
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
