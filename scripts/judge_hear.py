#!/usr/bin/env python3
"""HEAR Likert scores mapped to paper rec_raw (OLS).

  python scripts/judge_hear.py --target data/gens/pairs --out data/gens/hear.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hear import (  # noqa: E402
    ALL_FEAT,
    DEFAULT_JUDGE_MODEL,
    JUDGE_VERSION,
    score_receptiveness_likert0_signed_v5,
)
from lib import (  # noqa: E402
    add_common_args,
    append_jsonl,
    fit_hear_ols,
    load_jsonl_by_key,
    load_pairs,
    log,
    run_jobs,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    add_common_args(p)
    p.set_defaults(judge=DEFAULT_JUDGE_MODEL)
    return p.parse_args()


def jobs(pairs: list[dict], args: argparse.Namespace, ols) -> list[dict]:
    out = []
    for p in pairs:
        mk = str(p.get("model") or "").strip()
        pid = str(p["id"])
        key = f"{pid}|{mk}" if mk and f"|{mk}" not in pid else pid
        out.append(
            {
                "key": key,
                "id": key,
                "model": mk or None,
                "question": p["question"],
                "response": p["response"],
                "judge": args.judge,
                "service_tier": args.service_tier,
                "ols": ols,
            }
        )
    return out


async def worker(client, sem, job: dict) -> dict:
    parsed = await score_receptiveness_likert0_signed_v5(
        client,
        job["judge"],
        job["question"],
        job["response"],
        sem,
        retries=5,
        timeout=180.0,
        max_completion_tokens=1400,
        service_tier=job["service_tier"] or None,
    )
    x = np.array([[float(getattr(parsed, k)) for k in ALL_FEAT]], dtype=float)
    rec_raw = float(job["ols"].predict(x)[0])
    row = {
        "key": job["key"],
        "id": job["id"],
        "rec_raw": rec_raw,
        "judge": job["judge"],
        "judge_version": JUDGE_VERSION,
        **{k: float(getattr(parsed, k)) for k in ALL_FEAT},
    }
    if job.get("model"):
        row["model"] = job["model"]
    return row


def smoke_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        mk = str(p.get("model") or "").strip()
        pid = str(p["id"])
        key = f"{pid}|{mk}" if mk and f"|{mk}" not in pid else pid
        rows.append(
            {
                "key": key,
                "id": key,
                "model": mk or None,
                "rec_raw": 0.0,
                "judge": "smoke",
                "judge_version": JUDGE_VERSION,
                **{k: 0.0 for k in ALL_FEAT},
            }
        )
    return rows


async def main_async(args: argparse.Namespace) -> None:
    pairs = load_pairs(args.target)
    if args.limit:
        pairs = pairs[: args.limit]
    if args.smoke:
        for row in smoke_rows(pairs):
            append_jsonl(args.out, row)
        log(f"[hear smoke] wrote {args.out}")
        return
    ols = fit_hear_ols()
    all_jobs = jobs(pairs, args, ols)
    done = load_jsonl_by_key(args.out)
    await run_jobs(
        all_jobs, done, worker, args.out, concurrency=args.concurrency, label="hear"
    )


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
