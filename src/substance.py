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
