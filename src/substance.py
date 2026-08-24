"""Paired judge for original vs receptive rewrite QA.

Paper / analysis.R (98.5% verdict-preservation stat): uses verdict_same only.
Rewrites are not filtered on this judge; it is a post-hoc audit.

ok_hear, takeaway_same, and pass_all() were used in pilot rewrite repair
(attic scripts) and are stored in receptiveness_transform_judged.jsonl but do
not enter reported statistics or fig2 filtering.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JUDGE_VERSION = "receptivize_hear_substance_v5"
DEFAULT_JUDGE_MODEL = "gpt-5.6-luna"

# Production system prompt lives in scripts/judge_substance.py (SUBSTANCE_SYSTEM).


class ReceptivizeHearSubstanceJudgment(BaseModel):
    verdict_original: Literal["YTA", "NTA", "mixed", "other", "unclear"]
    verdict_rewrite: Literal["YTA", "NTA", "mixed", "other", "unclear"]
    verdict_same: Literal[0, 1]
    takeaway_same: Literal[0, 1]
    added_outside_facts: Literal[0, 1]
    dropped_loadbearing_reason: Literal[0, 1]
    logic_inverted: Literal[0, 1]
    false_acknowledgment: Literal[0, 1] = 0
    agreed_with_comment_not_user: Literal[0, 1] = 0
    rewrite_H: Literal[0, 1]
    rewrite_E: Literal[0, 1]
    rewrite_A: Literal[0, 1]
    rewrite_R: Literal[0, 1]
    rewrite_is_receptive: Literal[0, 1]
    original_H: Literal[0, 1]
    original_E: Literal[0, 1]
    original_A: Literal[0, 1]
    original_R: Literal[0, 1]
    original_is_receptive: Literal[0, 1]
    evidence_substance: str = Field(
        default="",
        description="Quote(s) supporting verdict/takeaway flags",
    )
    evidence_hear: str = Field(
        default="",
        description="Quote(s) supporting HEAR flags on the rewrite",
    )
    reasoning: str = ""


def pass_substance(j: ReceptivizeHearSubstanceJudgment) -> bool:
    return (
        int(j.verdict_same) == 1
        and int(j.takeaway_same) == 1
        and int(j.added_outside_facts) == 0
        and int(j.logic_inverted) == 0
        and int(j.false_acknowledgment) == 0
        and int(j.agreed_with_comment_not_user) == 0
    )


def pass_all(j: ReceptivizeHearSubstanceJudgment) -> bool:
    return pass_substance(j) and int(j.rewrite_is_receptive) == 1


def judgment_to_row(j: ReceptivizeHearSubstanceJudgment, **extra) -> dict:
    row = {
        "judge_version": JUDGE_VERSION,
        "verdict_original": j.verdict_original,
        "verdict_rewrite": j.verdict_rewrite,
        "verdict_same": int(j.verdict_same),
        "takeaway_same": int(j.takeaway_same),
        "added_outside_facts": int(j.added_outside_facts),
        "dropped_loadbearing_reason": int(j.dropped_loadbearing_reason),
        "logic_inverted": int(j.logic_inverted),
        "false_acknowledgment": int(j.false_acknowledgment),
        "agreed_with_comment_not_user": int(j.agreed_with_comment_not_user),
        "rewrite_H": int(j.rewrite_H),
        "rewrite_E": int(j.rewrite_E),
        "rewrite_A": int(j.rewrite_A),
        "rewrite_R": int(j.rewrite_R),
        "rewrite_is_receptive": int(j.rewrite_is_receptive),
        "original_H": int(j.original_H),
        "original_E": int(j.original_E),
        "original_A": int(j.original_A),
        "original_R": int(j.original_R),
        "original_is_receptive": int(j.original_is_receptive),
        "ok_substance": int(pass_substance(j)),
        "ok_hear": int(j.rewrite_is_receptive),
        "ok": int(pass_all(j)),
        "evidence_substance": j.evidence_substance,
        "evidence_hear": j.evidence_hear,
        "reasoning": j.reasoning,
    }
    row.update(extra)
    return row


def build_user_prompt(
    original: str,
    rewrite: str,
    post: str | None = None,
    *,
    post_note: str | None = None,
) -> str:
    parts = []
    if post and post.strip():
        note = post_note or (
            "POST (context only; original comment is the source of facts):"
        )
        parts.append(f"{note}\n{post.strip()}")
    parts.append(f"ORIGINAL COMMENT:\n{(original or '').strip()}")
    parts.append(f"REWRITE:\n{(rewrite or '').strip()}")
    return "\n\n".join(parts)


async def score_receptivize_hear_substance(
    client,
    model: str,
    original: str,
    rewrite: str,
    sem,
    *,
    post: str | None = None,
    retries: int = 5,
    timeout: float = 120.0,
    max_completion_tokens: int = 2000,
    service_tier: str | None = None,
    system: str,
    post_note: str | None = None,
) -> ReceptivizeHearSubstanceJudgment:
    import asyncio

    user = build_user_prompt(original, rewrite, post, post_note=post_note)
    last_err: Exception | None = None
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": ReceptivizeHearSubstanceJudgment,
        "max_completion_tokens": max_completion_tokens,
        "timeout": timeout,
    }
    if service_tier:
        kwargs["service_tier"] = service_tier

    for attempt in range(retries):
        try:
            from tpm_limit import acquire_luna_tpm, estimate_tokens
            import json as _json

            schema_chars = len(_json.dumps(ReceptivizeHearSubstanceJudgment.model_json_schema()))
            est = estimate_tokens(
                system + "\n" + user,
                max_out=max_completion_tokens,
                schema_chars=schema_chars,
            )
            await acquire_luna_tpm(est)
            async with sem:
                r = await client.beta.chat.completions.parse(**kwargs)
                parsed = r.choices[0].message.parsed
                if parsed is None:
                    raise RuntimeError(
                        f"empty parse finish_reason={r.choices[0].finish_reason}"
                    )
                return parsed
        except Exception as e:
            last_err = e
            await asyncio.sleep(min(2**attempt, 20))
    assert last_err is not None
    raise last_err
