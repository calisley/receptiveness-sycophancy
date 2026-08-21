#!/usr/bin/env python3
"""Luna YTA/NTA/mixed/other labels on (post, response) pairs.

  python scripts/judge_verdict.py --target data/mitigation/terra.jsonl --out data/mitigation/verdicts.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lib import add_common_args, append_jsonl, load_jsonl, load_jsonl_by_key, log, run_jobs  # noqa: E402
from verdict import VERDICT_SYSTEM, VerdictJudgment, judge_user_message  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--response-field", default="response", help="response | response_1p | response_3p")
    add_common_args(p)
    return p.parse_args()


def load_rows(path: Path) -> list[dict]:
    rows = load_jsonl(path)
    if rows:
        return rows
    from lib import load_pairs

    return load_pairs(path)


async def worker(client, sem, job: dict) -> dict:
    last = None
    for attempt in range(5):
        try:
            async with sem:
                r = await client.beta.chat.completions.parse(
                    model=job["judge"],
                    messages=[
                        {"role": "system", "content": VERDICT_SYSTEM},
                        {
                            "role": "user",
                            "content": judge_user_message(
                                post_1p=job["question"],
                                response=job["response"],
                                prompt_3p=job.get("prompt_3p"),
                            ),
                        },
                    ],
                    response_format=VerdictJudgment,
                    max_completion_tokens=400,
                    timeout=180.0,
                    service_tier=job["service_tier"] or None,
                )
            parsed = r.choices[0].message.parsed
            return {
                "key": job["key"],
                "id": job["id"],
                "arm": job["arm"],
                "verdict": parsed.verdict,
                "confidence": parsed.confidence,
                "brief_reason": parsed.brief_reason,
                "mixed_subtype": parsed.mixed_subtype,
                "judge": job["judge"],
            }
        except Exception as e:
            last = e
            await asyncio.sleep(min(2**attempt, 16))
    raise RuntimeError(last)


async def main_async(args: argparse.Namespace) -> None:
    rows = load_rows(args.target)
    if args.limit:
        rows = rows[: args.limit]
    jobs = []
    for r in rows:
        text = r.get(args.response_field) or r.get("response")
        q = r.get("prompt_1p") or r.get("question") or r.get("prompt")
        if not text or not q:
            continue
        jobs.append(
            {
                "key": f"{r.get('id')}|{args.response_field}",
                "id": r.get("id"),
                "arm": args.response_field,
                "question": q,
                "response": text,
                "prompt_3p": r.get("prompt_3p") if args.response_field == "response_3p" else None,
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
                    "arm": j["arm"],
                    "verdict": "YTA",
                    "confidence": "high",
                    "brief_reason": "smoke",
                    "mixed_subtype": "na",
                    "judge": "smoke",
                },
            )
        log(f"[verdict smoke] wrote {args.out}")
        return
    done = load_jsonl_by_key(args.out)
    await run_jobs(jobs, done, worker, args.out, concurrency=args.concurrency, label="verdict")


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
