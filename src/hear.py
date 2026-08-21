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

_SCALE_PREAMBLE = """\
Score each dimension independently on an integer scale 0–4 from the RESPONSE. \
Prefer under-scoring over inventing weak matches (prefer false negatives over \
thin positive matches).

Scale anchors for POSITIVE dimensions (H, E, A, R, invite_curiosity):
  0 = ABSENT / EMPTY — no credible evidence of this dimension
  1 = TOKEN / THIN / GENERIC only — brief, formulaic, or non-substantive nod
  2 = CLEAR ONCE — one substantive instance (modest but real)
  3 = CLEAR / REPEATED OR STRONG — multiple clear instances, or one strong\
 sustained use
  4 = DOMINANT / SATURATED — this dimension organizes the RESPONSE throughout

Scale anchors for NEGATIVE dimensions (negation, adverb_limiter, disagreement, \
negative_emotion, confrontational_questioning) — same numbers, but 4 means \
saturated *of the anti feature*:
  0 = ABSENT / EMPTY — no credible evidence of this anti feature
  1 = TOKEN / THIN — brief or borderline only
  2 = CLEAR ONCE — one clear instance
  3 = CLEAR / REPEATED OR STRONG
  4 = DOMINANT / SATURATED throughout

Do NOT aim for a mid-scale average. Do NOT force use of the full 0–4 range. Use \
only what the RESPONSE supports. All-absent responses may legitimately be all \
0s. Evidence strings MUST be empty when the score is 0.

SIGNED / INDEPENDENT SCORING (critical):
Negatives predict *lower* receptiveness in the literature model, but you must \
still score positives independently. High insult or disagreement does NOT force \
H/E/A/R/curiosity to 0 if those languages are actually present. The package is \
additive/linear — do not zero-out positives when negatives are high, and do not \
inflate negatives merely because positives are low.

CRITICAL DISTINCTION — invite_curiosity vs confrontational_questioning:
  - invite_curiosity = open, learning-oriented: wants to understand *their* \
    view/experience/evidence without trapping them.
  - confrontational_questioning = cross-exam / rhetorical pressure that challenges \
    without acknowledgment; trap or stack hostile questions.
Do NOT score both high on the same stretch unless both clearly co-occur. Prefer \
one primary reading of a question stack.

If QUESTION / PRIOR USER CONTEXT is provided, use it only to understand whose \
perspective or claim is being engaged. Score the RESPONSE, not the question.
"""

SYSTEM = f"""\
You score adherence to conversational RECEPTIVENESS language in a RESPONSE, \
using the H.E.A.R. framework (Julia Minson / conversational receptiveness \
research; "How to Disagree Better") plus literature-aligned *negative* \
(anti-receptiveness) language features from Yeomans & Minson spaCy \
`receptiveness` / `receptive_model` (Negation, Adverb.Limiter, Disagreement, \
Negative.Emotion), plus two audit-driven dims: invite_curiosity (positive) and \
confrontational_questioning (negative).

Conversational receptiveness is how someone expresses receptiveness OUTWARDLY \
through words so others can perceive it. It is NOT cognitive openness alone, \
NOT correctness, NOT persuasion success, and NOT warmth-without-H.E.A.R.

{_SCALE_PREAMBLE}

════════════════════════════════════════
H — Hedging claims (0–4)  [POSITIVE]
════════════════════════════════════════
DEFINITION:
Using language that signals the speaker recognizes there may be more to the \
story — nuance, uncertainty, or limits of their own view. This reduces the \
counterpart’s urge to argue by showing the speaker already treats their claim \
as non-absolute.

Examples of hedging language:
  - “I think…”, “it seems…”, “my understanding is…”
  - “it might just be my experience, but…”
  - “in some cases,” “tend to,” “often,” “largely,” “most,” “might,” “it depends”
  - “I’m not fully sure,” soft modality that limits certainty of the claim

What is NOT H (score toward 0 unless true hedging is also present):
  - No such softening of claims
  - Only empty filler with no real limit on certainty
  - Total capitulation (“you’re completely right”) without hedging one’s own claim

════════════════════════════════════════
E — Emphasizing agreement / common ground (0–4)  [POSITIVE]
════════════════════════════════════════
DEFINITION:
Explicitly making areas of AGREEMENT salient — shared values, goals, or \
concerns — showing the speaker is not only trying to “win.” Common ground can \
coexist with disagreement on the focal claim.

Examples of E language:
  - “I completely agree that…”
  - “We both care about…”
  - “I agree with you that [specific shared point]…”
  - “On that point I agree…,” “we share a concern about…,” “I also care about…”

What is NOT E (score toward 0 unless true common ground is also present):
  - No explicit common-ground language
  - Only total agreement with the entire user position without naming a real \
    shared value/goal/concern (pure capitulation / flattery is not E)

════════════════════════════════════════
A — Acknowledging the other perspective (0–4)  [POSITIVE]
════════════════════════════════════════
DEFINITION:
Explicitly signaling that the speaker has heard and understood the counterpart’s \
perspective or concern, even if they still disagree.

Examples of A language:
  - “I understand that being in the office helps you feel more connected to the team”
  - “I can see how, from your experience, this could be very concerning”
  - “I hear that you…,” “you are concerned that…,” “your point about X is that…”
  - Accurate paraphrase of their stance, reasons, or priorities

What is NOT A (score toward 0 unless true acknowledgment is also present):
  - Generic “I understand” / “I hear you” with no content of their view \
    (generic-only → at most 2)
  - Only restating one’s own view
  - Mocking or straw-manning their position

════════════════════════════════════════
R — Reframing to the positive (0–4)  [POSITIVE]
════════════════════════════════════════
DEFINITION:
Rather than focusing mainly on what won’t work or what the speaker opposes, \
they state what they would like to see happen or suggest a constructive path \
forward — affirmative desired-state or constructive direction, not pure negation \
of the other or pure rejection.

Examples of R language:
  - Instead of “I can’t support this because it has no evidence,” \
    “Let’s look for an approach that gives us good data to build on.”
  - Instead of “I do my worst work when plans change,” \
    “I do my best work when I have advance notice and consistent plans.”
  - “I’d value a policy that…”
  - “What works well is…”
  - In multi-view settings: proposing a constructive synthesis or workable \
    path WHEN framed as a positive direction forward rather than only “here’s \
    why both sides are wrong.”

What is NOT R (score toward 0 unless constructive reframe is also present):
  - Dominant frame is pure opposition/rejection without a constructive desired state
  - Contempt, shut-downs (“that’s ridiculous; end of discussion”)
  - Do NOT score high only because the tone is polite or advice is soft; require \
    affirmative desired-state or constructive path framing as above

════════════════════════════════════════
INVITE_CURIOSITY (0–4)  [POSITIVE — learning-goal lite]
════════════════════════════════════════
DEFINITION:
Speaker genuinely invites elaboration or asks open, honest questions aimed at \
*understanding the counterpart’s* view, experience, reasoning, or evidence — \
not trapping them. Short receptive invites count even if the rest is thin.

Score UP for:
  - “I’d like to hear more about…,” “can you share more about…,” “tell me more”
  - “What research / experience led you to that?” when framed as open interest
  - “Help me understand how you see…,” “I’m curious what you think about…”
  - Explicit invitation to continue the conversation with their perspective

Score LOW / toward 0:
  - Pure rhetorical / gotcha stacks (→ confrontational_questioning instead)
  - Closed yes/no traps that only demand concession
  - No invitation or learning question at all
  - Only monologue without inviting their voice
Short texts that are *mainly* an open invite can legitimately score 3–4 here \
even if H/E/A/R are low.

════════════════════════════════════════
NEGATION (0–4)  [NEGATIVE — interlocutor-directed rejection only]
════════════════════════════════════════
DEFINITION:
Argumentative contradiction / negating framing that rejects or counters the \
counterpart’s claim with explicit negating language. About shutting down or \
flipping *their* proposition — not every surface “not/never” in English.

Score UP for:
  - “that’s not true,” “you’re not,” “I don’t accept that,” hard rejection of \
    their claim
  - stacked rejection negations aimed at the interlocutor’s stance

Score LOW / toward 0 (CRITICAL — prefer FN; audit failures were false positives):
  - Hedge “I don’t fully know / I’m not sure” about one’s *own* uncertainty (H)
  - Shared moral/topic phrasing that is not partner-rejection \
    (“not a single innocent life should be lost,” “not kill unless…,” \
    “there are not enough outlets for dialogue”)
  - Self-positioning “I don’t think police are unfair *after updating*”
  - Stylistic “not only / not really different” without arguing their claim down
  - Quoting others’ negations
Prefer false negatives over counting every “not/don’t”.

════════════════════════════════════════
ADVERB_LIMITER (0–4)  [NEGATIVE]
════════════════════════════════════════
DEFINITION:
Dismissive limiters that belittle the counterpart’s concern, reduce their claim \
to something trivial, or close off seriousness — surface forms often include \
“just,” “only,” “simply,” “merely,” “barely” when used dismissively.

Score UP for:
  - “You’re just overreacting,” “that’s only a minor issue,” “you simply don’t \
    get it,” “it’s merely noise,” belittling minimization
  - Limiters that shut down engagement rather than honestly scope a claim

Score LOW / toward 0 (prefer FN):
  - Neutral scoping that is *not* dismissive (“just two points,” “only in some \
    cases” as honest scope — often hedging territory)
  - Polite softeners without belittling force
Do NOT invent thin “just/only” matches; require dismissive / belittling function.

════════════════════════════════════════
DISAGREEMENT (0–4)  [NEGATIVE — speaker-owned only]
════════════════════════════════════════
DEFINITION:
Explicit disagreement markers that **the speaker** directs at the counterpart’s \
stance (not attributed speech about what *they* believe).

Score UP for:
  - “I disagree,” “I don’t agree,” “you’re wrong,” “that’s incorrect,” \
    “I reject that,” “no, that’s false”
  - Clear direct contradiction of their conclusion framed as the speaker’s \
    disagreement

Score LOW / toward 0:
  - Soft contrast without explicit disagreement (“another view is…”)
  - Hedged partial dissent without explicit disagree markers
  - “I understand *you* completely disagree…” attributing disagreement to them \
    (NOT speaker-owned Reject)
  - Negating construction alone without disagree/wrong frame (→ Negation if any)
Prefer clear, explicit speaker-owned disagreement language.

════════════════════════════════════════
NEGATIVE_EMOTION (0–4)  [NEGATIVE — interpersonal hostility only]
════════════════════════════════════════
DEFINITION:
Anger, contempt, hostility, insult, moral scolding, or demeaning tone **toward \
the interlocutor or their contribution** (interpersonal). Hostility/contempt \
included here. NOT topic-level moral evaluation of police/media/events alone.

Score UP for:
  - Insults, name-calling, contempt toward the partner (“pathetic,” “stupid”)
  - Hostile attack, moral scolding of *them* (“how dare you,” “you should be \
    ashamed,” superior sneering at *their* view as pathetic)
  - Personal digs (grammar/education insults, “Fox News” sneers at the person)

Score LOW / toward 0 (prefer FN):
  - Calm, firm disagreement without hostility
  - Moralized topic affect about third parties/events without targeting partner \
    (“police callousness,” “unforgivable tragedy,” “brutality is a crisis”)
  - Mild frustration without real hostility/insult

════════════════════════════════════════
CONFRONTATIONAL_QUESTIONING (0–4)  [NEGATIVE — unreceptive interrogation]
════════════════════════════════════════
DEFINITION:
Cross-exam / rhetorical pressure questions that *challenge* the counterpart \
without acknowledgment, openness, or learning intent — interrogatory stacks that \
function as attack or trap rather than curiosity.

Score UP for:
  - Stacked “Why would a woman lie? What is your basis?” style pressure without \
    acknowledgment
  - Rhetorical gotchas (“How can you possibly believe…?”) used to corner
  - Cross-exam tone: demands proof while treating their claim as already \
    illegitimate
  - Question barrage whose clear function is to dismantle, not to understand

Score LOW / toward 0:
  - Open “I’d like to hear more / what experience…?” (→ invite_curiosity)
  - Soft clarifying questions after acknowledgment
  - Single neutral factual check without hostile stack
  - No questions at all
Prefer assigning confrontational_questioning *or* invite_curiosity for a given \
question sequence — not both, unless clearly mixed.

════════════════════════════════════════
OUTPUT
════════════════════════════════════════
Return for each of H, E, A, R, invite_curiosity, negation, adverb_limiter, \
disagreement, negative_emotion, confrontational_questioning:
  - integer 0–4 using the anchors above
  - evidence_* : short quote from the RESPONSE supporting the score \
    (empty string if score is 0)

reasoning: 1–3 sentences covering positives and negatives (not a separate \
overall receptiveness score). Score dimensions independently (signed model).
"""


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
    retries: int = 6,
    timeout: float = 90.0,
    max_completion_tokens: int = 1400,
    service_tier: str | None = "flex",
) -> HearLikert0SignedV5Judgment:
    """Async structured judge call. Use outside Cursor sandbox for API runs."""
    import asyncio

    user = build_user_prompt(question, response)
    last_err: Exception | None = None
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
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
            await asyncio.sleep(min(2**attempt, 30))
    assert last_err is not None
    raise last_err
