"""
LLM judge for H.E.A.R. conversational-receptiveness — Likert 0–4 signed (v5).

v5 = v4 (tight N / Dis / NegEmo) + two new dims from residual audit:
  - invite_curiosity (POSITIVE): open learning invites / honest question to understand
  - confrontational_questioning (NEGATIVE): cross-exam / rhetorical pressure questions

Scale: 0=absent/empty … 4=saturated. JUDGE_VERSION = receptiveness_hear_v5_likert0_signed
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JUDGE_VERSION = "receptiveness_hear_v5_likert0_signed"
DEFAULT_JUDGE_MODEL = "gpt-5.6-luna"
SCALE_MIN = 0
SCALE_MAX = 4

POSITIVE_FEAT = [
    "hedging",
    "emphasize_agreement",
    "acknowledge_perspective",
    "reframe_positive",
    "invite_curiosity",
]
NEGATIVE_FEAT = [
    "negation",
    "adverb_limiter",
    "disagreement",
    "negative_emotion",
    "confrontational_questioning",
]
ALL_FEAT = POSITIVE_FEAT + NEGATIVE_FEAT

# Judge system prompt lives in scripts/judge_hear.py (HEAR_SYSTEM).
# score_receptiveness_likert0_signed_v5 requires system= from the caller.


class HearLikert0SignedV5Judgment(BaseModel):
    hedging: Literal[0, 1, 2, 3, 4] = Field(
        description="H: hedges / non-absolute claims (0=absent … 4=saturated)"
    )
    emphasize_agreement: Literal[0, 1, 2, 3, 4] = Field(
        description="E: common ground / partial agreement (0=absent … 4=saturated)"
    )
    acknowledge_perspective: Literal[0, 1, 2, 3, 4] = Field(
        description="A: acknowledges / paraphrases other view (0=absent … 4=saturated)"
    )
    reframe_positive: Literal[0, 1, 2, 3, 4] = Field(
        description="R: constructive desired-state / positive reframe (0–4)"
    )
    invite_curiosity: Literal[0, 1, 2, 3, 4] = Field(
        description="Invite elaboration / open learning questions (0–4)"
    )
    negation: Literal[0, 1, 2, 3, 4] = Field(
        description="Interlocutor-directed argumentative rejection (0–4)"
    )
    adverb_limiter: Literal[0, 1, 2, 3, 4] = Field(
        description="Dismissive limiters just/only/simply/merely (0–4)"
    )
    disagreement: Literal[0, 1, 2, 3, 4] = Field(
        description="Speaker-owned explicit disagreement (0–4)"
    )
    negative_emotion: Literal[0, 1, 2, 3, 4] = Field(
        description="Interpersonal hostility/contempt/personal digs (0–4)"
    )
    confrontational_questioning: Literal[0, 1, 2, 3, 4] = Field(
        description="Cross-exam / rhetorical pressure questions (0–4)"
    )
    evidence_hedging: str = ""
    evidence_emphasize_agreement: str = ""
    evidence_acknowledge: str = ""
    evidence_reframe_positive: str = ""
    evidence_invite_curiosity: str = ""
    evidence_negation: str = ""
    evidence_adverb_limiter: str = ""
    evidence_disagreement: str = ""
    evidence_negative_emotion: str = ""
    evidence_confrontational_questioning: str = ""
    reasoning: str = ""


def positive_sum(j: HearLikert0SignedV5Judgment) -> int:
    return sum(int(getattr(j, k)) for k in POSITIVE_FEAT)


def positive_mean(j: HearLikert0SignedV5Judgment) -> float:
    return positive_sum(j) / float(len(POSITIVE_FEAT))


def negative_sum(j: HearLikert0SignedV5Judgment) -> int:
    return sum(int(getattr(j, k)) for k in NEGATIVE_FEAT)


def negative_mean(j: HearLikert0SignedV5Judgment) -> float:
    return negative_sum(j) / float(len(NEGATIVE_FEAT))


def hear_sum(j: HearLikert0SignedV5Judgment) -> int:
    """Legacy alias: original HEAR four positives only."""
    return (
        int(j.hedging)
        + int(j.emphasize_agreement)
        + int(j.acknowledge_perspective)
        + int(j.reframe_positive)
    )


def hear_mean(j: HearLikert0SignedV5Judgment) -> float:
    return hear_sum(j) / 4.0


def judgment_to_row(j: HearLikert0SignedV5Judgment, **extra) -> dict:
    row = {
        "judge_version": JUDGE_VERSION,
        **{k: int(getattr(j, k)) for k in ALL_FEAT},
        "hear_sum": hear_sum(j),
        "hear_mean": hear_mean(j),
        "positive_sum": positive_sum(j),
        "positive_mean": positive_mean(j),
        "negative_sum": negative_sum(j),
        "negative_mean": negative_mean(j),
        "evidence_hedging": j.evidence_hedging,
        "evidence_emphasize_agreement": j.evidence_emphasize_agreement,
        "evidence_acknowledge": j.evidence_acknowledge,
        "evidence_reframe_positive": j.evidence_reframe_positive,
        "evidence_invite_curiosity": j.evidence_invite_curiosity,
        "evidence_negation": j.evidence_negation,
        "evidence_adverb_limiter": j.evidence_adverb_limiter,
        "evidence_disagreement": j.evidence_disagreement,
        "evidence_negative_emotion": j.evidence_negative_emotion,
        "evidence_confrontational_questioning": j.evidence_confrontational_questioning,
        "reasoning": j.reasoning,
    }
    row.update(extra)
    return row


def build_user_prompt(question: str | None, response: str) -> str:
    q = (question or "").strip()
    r = (response or "").strip()
    if q:
        return f"QUESTION / PRIOR USER CONTEXT:\n{q}\n\nRESPONSE TO SCORE:\n{r}"
    return f"RESPONSE TO SCORE:\n{r}"


async def score_receptiveness_likert0_signed_v5(
    client,
    model: str,
    question: str | None,
    response: str,
    sem,
    *,
    system: str,
    retries: int = 6,
    timeout: float = 90.0,
    max_completion_tokens: int = 1400,
    service_tier: str | None = "flex",
) -> HearLikert0SignedV5Judgment:
    """Async structured judge call. ``system`` = scripts/judge_hear.py HEAR_SYSTEM."""
    import asyncio

    user = build_user_prompt(question, response)
    last_err: Exception | None = None
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": HearLikert0SignedV5Judgment,
        "max_completion_tokens": max_completion_tokens,
        "timeout": timeout,
    }
    if service_tier:
        kwargs["service_tier"] = service_tier

    for attempt in range(retries):
        try:
            # Token-budget before taking a concurrency slot.
            from tpm_limit import acquire_luna_tpm, estimate_tokens
            import json as _json

            schema_chars = len(_json.dumps(HearLikert0SignedV5Judgment.model_json_schema()))
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
            msg = str(e).lower()
            # Brief pause on TPM 429s; bucket will also gate retries.
            if "rate_limit" in msg or "429" in msg:
                await asyncio.sleep(0.2)
            else:
                await asyncio.sleep(min(2**attempt, 30))
    assert last_err is not None
    raise last_err
