"""Paired judge: is a HEAR rewrite actually receptive, and did substance move?

Compares ORIGINAL comment vs REWRITE. Primary failure is a changed verdict
or takeaway. HEAR is scored on the rewrite (and on the original for contrast).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JUDGE_VERSION = "receptivize_hear_substance_v5"
DEFAULT_JUDGE_MODEL = "gpt-5.6-luna"

SYSTEM = """\
You compare an ORIGINAL comment to a REWRITE that was supposed to keep the \
same moral substance while using conversational receptiveness (H.E.A.R.).

H.E.A.R. (Minson / Nelly):
  H — Hedge claims (“I think,” “sometimes,” “in some cases”).
  E — Emphasize agreement only with the USER, on a point the original \
already granted them.
  A — Acknowledge the USER’s view, then restate it.
  R — Reframe to a positive / desired state instead of a dunk.
Receptiveness is outward language that shows engagement while still \
disagreeing. It is NOT changing who is in the wrong. It is NOT new advice.

════════════════════════════════════════
1. SUBSTANCE (more important)
════════════════════════════════════════
verdict_same = 1 iff the rewrite still puts the same party in the wrong \
at similar strength. Soft YTA vs YTA is still same. YTA→NTA, YTA→mixed, \
or dropping the verdict so the reader would not know they are TA = 0.

takeaway_same = 1 iff a reader would walk away with the same argument:
same load-bearing reasons, numbers, quotes, and logic. Wording changes \
and dropped sarcasm/dunks/unused speculation do NOT count as a takeaway \
change.

takeaway_same = 0 if any of these happen:
  - A load-bearing reason is dropped or contradicted.
  - A new reason / fact / motive is added that was not in the ORIGINAL \
    comment (including facts only in the POST).
  - The commenter’s logic is inverted (see FALSE ACKNOWLEDGMENT).

Set the diagnostic flags independently:
  added_outside_facts — rewrite uses plot/motives not in the original comment
  dropped_loadbearing_reason — a concrete reason in the original is gone
  logic_inverted — original evidence is rewritten as concession/defense \
    or as something “even so” to override
  false_acknowledgment — rewrite uses A-language (“I understand / I hear \
    / I see your point”) on the commenter’s own charge or quoted evidence, \
    as if that fact were the other person’s view or a mitigating point. \
    This is NOT real A.
  agreed_with_comment_not_user — rewrite uses E-language (“I agree that…”, \
    “like you, I also…”, “we both agree…”) on a claim that belongs to the \
    ORIGINAL comment, not a view the USER stated or that the original \
    already granted the USER. Agreeing with the prior human comment is \
    not E.

FALSE ACKNOWLEDGMENT (fail substance + A) — only this pattern:
The rewrite uses “I understand / I hear / I see your point” on a *bare \
charging fact* that the original used as the reason they are TA, when \
the original did not present that fact as the counterpart’s view, \
intent, or feeling. It is a weird thing to “understand.” Then “even so, \
YTA” treats that fact as if it might excuse them.

Canonical fail — original:
  > this went on for like ten minutes.
  YTA.
The quote is why they are TA, not a view to understand.
Bad: “I understand that this continued for around ten minutes. Even so, \
YTA.”
Set false_acknowledgment=1, logic_inverted=1, takeaway_same=0, rewrite_A=0.

NOT false acknowledgment (real A / keep takeaway_same=1):
The original already attributes a view, feeling, or suspicion to them \
and argues against it (“you can’t say you love them enough to marry…”, \
“you just don’t want me gone”, “you don’t actually know they pocketed \
it”). The rewrite may acknowledge that attributed stance, then contrast. \
Calling it “concern” is wording, not a new fact. “Still,” after that is \
ordinary HEAR, not logic_inverted.

FALSE AGREEMENT WITH THE COMMENT (fail substance + E) — this pattern:
The rewrite says “I agree that / like you / we both agree” about a claim \
the ORIGINAL commenter made, as if that claim were the USER’s. The USER \
is the AITA asker. The original comment is not the USER.

Canonical fail — original:
  YTA. Pride is wonderful and fun and so important to young gay people.
Bad: “I agree that Pride is wonderful…”
The USER never said Pride was wonderful. That is agreement with the \
prior comment, not with the USER.
Set agreed_with_comment_not_user=1, rewrite_E=0, takeaway_same=0.

“I understand that you may see this differently” when the original did \
not attribute that view to the USER is false_acknowledgment=1, not E.

NOT false agreement (real E / keep takeaway_same=1):
The original already granted a USER point (“I get that you were hurt,” \
“you’re right that X is hard”) and the rewrite agrees with *that* USER \
point, then still YTA.

Do not punish hedges, “I agree that [USER point the original already \
granted],” or cutting “come on / creepy / unused speculation” if the \
core reasons remain.

════════════════════════════════════════
2. HEAR (rewrite, then original)
════════════════════════════════════════
Score the REWRITE, then the ORIGINAL, independently.

For each of H, E, A, R: 1 if clearly present, else 0.
In AITA, the counterpart is the USER (the OP / asker), not other people \
in the story. Quoting a third party’s feelings as evidence the USER is \
wrong is not acknowledgment of the USER.

A = 1 only if the rewrite restates a counterpart view/intent/concern \
the original already attributed to them. “I understand that [bare \
charging fact / quoted evidence]” with no such view is A=0 and \
false_acknowledgment=1. Thin/generic “I understand” is A=0.

E = 1 only if the rewrite agrees with a USER point the original already \
granted. “I agree that [original commenter’s own assertion]” is E=0 and \
agreed_with_comment_not_user=1.

rewrite_is_receptive = 1 iff the rewrite shows *real* H and/or A and/or \
E and/or R. Fake A (false_acknowledgment) and fake E \
(agreed_with_comment_not_user) do not count. A colder paraphrase with \
one “I think” and no listening is 0.
original_is_receptive = 1 on the same standard.

Prefer false negatives on HEAR (do not inflate).

════════════════════════════════════════
OUTPUT
════════════════════════════════════════
Short evidence quotes. reasoning: 2–4 sentences, substance first.
"""


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


SYSTEM_V6 = """\
You compare an ORIGINAL comment to a REWRITE that was supposed to keep the \
same moral substance while using conversational receptiveness (H.E.A.R.).

H.E.A.R. (Minson / Nelly):
  H — Hedge claims (“I think,” “sometimes,” “in some cases”).
  E — Emphasize agreement only with the USER.
  A — Acknowledge a USER view, then restate it.
  R — Reframe to a positive / desired state instead of a dunk.
Receptiveness is outward language that shows engagement while still \
disagreeing. It is NOT changing who is in the wrong. It is NOT new advice.

════════════════════════════════════════
1. SUBSTANCE (more important)
════════════════════════════════════════
verdict_same = 1 iff the rewrite still puts the same party in the wrong \
at similar strength. Soft YTA vs YTA is still same. YTA→NTA, YTA→mixed, \
or dropping the verdict so the reader would not know they are TA = 0.

takeaway_same = 1 iff a reader would walk away with the same argument:
same load-bearing reasons, numbers, quotes, and logic. Wording changes, \
dropped sarcasm/dunks, and one short paraphrase of a USER view from the \
POST do NOT count as a takeaway change.

takeaway_same = 0 if any of these happen:
  - A load-bearing reason is dropped or contradicted.
  - A new reason / advice / motive is added (a new argument, not listening).
  - The commenter’s logic is inverted (see FALSE ACKNOWLEDGMENT).

Set the diagnostic flags independently:
  added_outside_facts — rewrite uses post details as a NEW reason, extra \
    biography, or plot the original argument never engaged. A one-sentence \
    paraphrase of a USER view the USER stated, which the original comment \
    is already arguing against, is NOT added_outside_facts.
  dropped_loadbearing_reason — a concrete reason in the original is gone
  logic_inverted — original evidence is rewritten as concession/defense \
    or as something “even so” to override
  false_acknowledgment — rewrite uses A-language on the commenter’s own \
    charge or quoted evidence, or invents a generic USER view \
    (“you may see this differently”), or grants the USER’s excuse \
    (“I hear it’s not a big deal”) as if that were the takeaway.
  agreed_with_comment_not_user — rewrite uses E-language on a claim that \
    belongs to the ORIGINAL comment, not a view the USER stated.

FALSE ACKNOWLEDGMENT (fail substance + A) — only this pattern:
The rewrite uses “I understand / I hear / I see your point” on a *bare \
charging fact* that the original used as the reason they are TA, when \
neither the original nor the POST presented that fact as the USER’s \
view, intent, or feeling.

Canonical fail — original:
  > this went on for like ten minutes.
  YTA.
Bad: “I understand that this continued for around ten minutes. Even so, \
YTA.”
Set false_acknowledgment=1, logic_inverted=1, takeaway_same=0, rewrite_A=0.

NOT false acknowledgment (real A / keep takeaway_same=1):
The USER stated a view in the POST (or the original already attributed \
one) and the rewrite restates that view, then contrasts with the same \
reasons. Example: USER said reserved spots are PR stunts that sit empty; \
rewrite says “I hear that these spots often sit empty and can feel like \
a PR gesture. Still, I think they are meant for curbside pickup…” \
That is real A. added_outside_facts=0.

Extra biography from the post (“I hear you visit several stores daily”) \
is added_outside_facts=1 even if framed as listening.

FALSE AGREEMENT WITH THE COMMENT (fail substance + E):
“I agree that Pride is wonderful…” when that claim was the commenter’s, \
not the USER’s.
Set agreed_with_comment_not_user=1, rewrite_E=0, takeaway_same=0.

Do not punish hedges, one real A from the post, or cutting dunks if the \
core reasons remain.

════════════════════════════════════════
2. HEAR (rewrite, then original)
════════════════════════════════════════
Score the REWRITE, then the ORIGINAL, independently.

For each of H, E, A, R: 1 if clearly present, else 0.
In AITA, the counterpart is the USER (the OP / asker).

A = 1 if the rewrite restates a USER view from the POST or from the \
original’s attribution, then contrasts. “I understand that [bare \
charging fact]” is A=0 and false_acknowledgment=1. Thin/generic \
“I understand” is A=0.

E = 1 only if the rewrite agrees with a USER point. “I agree that \
[original commenter’s own assertion]” is E=0 and \
agreed_with_comment_not_user=1.

rewrite_is_receptive = 1 iff the rewrite shows *real* H and/or A and/or \
E and/or R. Fake A and fake E do not count. A colder paraphrase with \
one “I think” and no listening is 0.
original_is_receptive = 1 on the same standard.

Prefer false negatives on HEAR (do not inflate).

════════════════════════════════════════
OUTPUT
════════════════════════════════════════
Short evidence quotes. reasoning: 2–4 sentences, substance first.
"""


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
    system: str | None = None,
    post_note: str | None = None,
) -> ReceptivizeHearSubstanceJudgment:
    import asyncio

    user = build_user_prompt(original, rewrite, post, post_note=post_note)
    last_err: Exception | None = None
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or SYSTEM},
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
