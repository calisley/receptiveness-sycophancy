"""Paired judge for original vs receptive rewrite QA.

Paper / analysis.R: uses verdict_same only on the full fig-2 rewrite panel
(n = 1,892). Rewrites are not filtered on this judge; it is a post-hoc audit.
"""
from __future__ import annotations

from typing import Literal, Type

from pydantic import BaseModel

JUDGE_VERSION = "verdict_preservation"
DEFAULT_JUDGE_MODEL = "gpt-5.6-luna"

# Production system prompts live in scripts/judge_substance.py.


class VerdictPreservationJudgment(BaseModel):
    verdict_original: Literal["YTA", "NTA", "mixed", "other", "unclear"]
    verdict_rewrite: Literal["YTA", "NTA", "mixed", "other", "unclear"]
    verdict_same: Literal[0, 1]


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


async def _score_parsed(
    client,
    model: str,
    original: str,
    rewrite: str,
    sem,
    *,
    post: str | None = None,
    retries: int = 5,
    timeout: float = 120.0,
    max_completion_tokens: int = 1024,
    service_tier: str | None = None,
    system: str,
    response_format: Type[BaseModel],
    post_note: str | None = None,
) -> BaseModel:
    import asyncio

    user = build_user_prompt(original, rewrite, post, post_note=post_note)
    last_err: Exception | None = None
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": response_format,
        "max_completion_tokens": max_completion_tokens,
        "timeout": timeout,
    }
    if service_tier:
        kwargs["service_tier"] = service_tier

    for attempt in range(retries):
        try:
            from tpm_limit import acquire_luna_tpm, estimate_tokens
            import json as _json

            schema_chars = len(_json.dumps(response_format.model_json_schema()))
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


async def score_verdict_preservation(
    client,
    model: str,
    original: str,
    rewrite: str,
    sem,
    *,
    post: str | None = None,
    retries: int = 5,
    timeout: float = 120.0,
    max_completion_tokens: int = 1024,
    service_tier: str | None = None,
    system: str,
    post_note: str | None = None,
) -> VerdictPreservationJudgment:
    parsed = await _score_parsed(
        client,
        model,
        original,
        rewrite,
        sem,
        post=post,
        retries=retries,
        timeout=timeout,
        max_completion_tokens=max_completion_tokens,
        service_tier=service_tier,
        system=system,
        response_format=VerdictPreservationJudgment,
        post_note=post_note,
    )
    assert isinstance(parsed, VerdictPreservationJudgment)
    return parsed
