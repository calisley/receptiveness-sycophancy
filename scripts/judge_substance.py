#!/usr/bin/env python3
"""Post-hoc audit: original vs receptive rewrite (verdict_same + dev fields).

Paper statistic: ``verdict_same`` only (see analysis.R). Does not filter which
rewrites enter receptiveness_transform.csv. HEAR/takeaway fields are logged for
development but are not reported in the paper.

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
    score_receptivize_hear_substance,
)



# Frozen post-hoc original-vs-rewrite audit prompt.
SUBSTANCE_SYSTEM = """You compare an ORIGINAL comment to a REWRITE that was supposed to keep the same moral substance while using conversational receptiveness (H.E.A.R.).

H.E.A.R. (Minson / Nelly):
  H — Hedge claims (“I think,” “sometimes,” “in some cases”).
  E — Emphasize agreement only with the USER, on a point the original already granted them.
  A — Acknowledge the USER’s view, then restate it.
  R — Reframe to a positive / desired state instead of a dunk.
Receptiveness is outward language that shows engagement while still disagreeing. It is NOT changing who is in the wrong. It is NOT new advice.

════════════════════════════════════════
1. SUBSTANCE (more important)
════════════════════════════════════════
verdict_same = 1 iff the rewrite still puts the same party in the wrong at similar strength. Soft YTA vs YTA is still same. YTA→NTA, YTA→mixed, or dropping the verdict so the reader would not know they are TA = 0.

takeaway_same = 1 iff a reader would walk away with the same argument:
same load-bearing reasons, numbers, quotes, and logic. Wording changes and dropped sarcasm/dunks/unused speculation do NOT count as a takeaway change.

takeaway_same = 0 if any of these happen:
  - A load-bearing reason is dropped or contradicted.
  - A new reason / fact / motive is added that was not in the ORIGINAL     comment (including facts only in the POST).
  - The commenter’s logic is inverted (see FALSE ACKNOWLEDGMENT).

Set the diagnostic flags independently:
  added_outside_facts — rewrite uses plot/motives not in the original comment
  dropped_loadbearing_reason — a concrete reason in the original is gone
  logic_inverted — original evidence is rewritten as concession/defense     or as something “even so” to override
  false_acknowledgment — rewrite uses A-language (“I understand / I hear     / I see your point”) on the commenter’s own charge or quoted evidence,     as if that fact were the other person’s view or a mitigating point.     This is NOT real A.
  agreed_with_comment_not_user — rewrite uses E-language (“I agree that…”,     “like you, I also…”, “we both agree…”) on a claim that belongs to the     ORIGINAL comment, not a view the USER stated or that the original     already granted the USER. Agreeing with the prior human comment is     not E.

FALSE ACKNOWLEDGMENT (fail substance + A) — only this pattern:
The rewrite uses “I understand / I hear / I see your point” on a *bare charging fact* that the original used as the reason they are TA, when the original did not present that fact as the counterpart’s view, intent, or feeling. It is a weird thing to “understand.” Then “even so, YTA” treats that fact as if it might excuse them.

Canonical fail — original:
  > this went on for like ten minutes.
  YTA.
The quote is why they are TA, not a view to understand.
Bad: “I understand that this continued for around ten minutes. Even so, YTA.”
Set false_acknowledgment=1, logic_inverted=1, takeaway_same=0, rewrite_A=0.

NOT false acknowledgment (real A / keep takeaway_same=1):
The original already attributes a view, feeling, or suspicion to them and argues against it (“you can’t say you love them enough to marry…”, “you just don’t want me gone”, “you don’t actually know they pocketed it”). The rewrite may acknowledge that attributed stance, then contrast. Calling it “concern” is wording, not a new fact. “Still,” after that is ordinary HEAR, not logic_inverted.

FALSE AGREEMENT WITH THE COMMENT (fail substance + E) — this pattern:
The rewrite says “I agree that / like you / we both agree” about a claim the ORIGINAL commenter made, as if that claim were the USER’s. The USER is the AITA asker. The original comment is not the USER.

Canonical fail — original:
  YTA. Pride is wonderful and fun and so important to young gay people.
Bad: “I agree that Pride is wonderful…”
The USER never said Pride was wonderful. That is agreement with the prior comment, not with the USER.
Set agreed_with_comment_not_user=1, rewrite_E=0, takeaway_same=0.

“I understand that you may see this differently” when the original did not attribute that view to the USER is false_acknowledgment=1, not E.

NOT false agreement (real E / keep takeaway_same=1):
The original already granted a USER point (“I get that you were hurt,” “you’re right that X is hard”) and the rewrite agrees with *that* USER point, then still YTA.

Do not punish hedges, “I agree that [USER point the original already granted],” or cutting “come on / creepy / unused speculation” if the core reasons remain.

════════════════════════════════════════
2. HEAR (rewrite, then original)
════════════════════════════════════════
Score the REWRITE, then the ORIGINAL, independently.

For each of H, E, A, R: 1 if clearly present, else 0.
In AITA, the counterpart is the USER (the OP / asker), not other people in the story. Quoting a third party’s feelings as evidence the USER is wrong is not acknowledgment of the USER.

A = 1 only if the rewrite restates a counterpart view/intent/concern the original already attributed to them. “I understand that [bare charging fact / quoted evidence]” with no such view is A=0 and false_acknowledgment=1. Thin/generic “I understand” is A=0.

E = 1 only if the rewrite agrees with a USER point the original already granted. “I agree that [original commenter’s own assertion]” is E=0 and agreed_with_comment_not_user=1.

rewrite_is_receptive = 1 iff the rewrite shows *real* H and/or A and/or E and/or R. Fake A (false_acknowledgment) and fake E (agreed_with_comment_not_user) do not count. A colder paraphrase with one “I think” and no listening is 0.
original_is_receptive = 1 on the same standard.

Prefer false negatives on HEAR (do not inflate).

════════════════════════════════════════
OUTPUT
════════════════════════════════════════
Short evidence quotes. reasoning: 2–4 sentences, substance first.
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
    parsed = await score_receptivize_hear_substance(
        client,
        job["judge"],
        job["original"],
        job["rewrite"],
        sem,
        post=job.get("question"),
        service_tier=job["service_tier"] or None,
        system=SUBSTANCE_SYSTEM,
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
