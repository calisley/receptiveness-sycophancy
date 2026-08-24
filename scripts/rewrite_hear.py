#!/usr/bin/env python3
"""Keep-verdict HEAR rewrite of stored drafts.

  python scripts/rewrite_hear.py --style own_draft --target drafts.jsonl \\
      --out data/mitigation/hear_1p.jsonl --out-source hear
  python scripts/rewrite_hear.py --style listen_once --target human.jsonl \\
      --out data/gens/rewrites.jsonl

Bare ``--out-source hear`` expands to ``{model}|hear`` when the target row has
``model`` (multi-model gens). Fig2 human rewrites keep default ``rewrite``.

Prompts are inlined (frozen) so this package does not need a prompts/ tree.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lib import (  # noqa: E402
    MODELS,
    add_common_args,
    append_jsonl,
    gen_client,
    load_jsonl,
    load_jsonl_by_key,
    load_pairs,
    log,
    model_slug,
    run_jobs,
    tracked_client,
)

# Frozen own_draft system (mitigation rewrite of model drafts).
OWN_DRAFT_SYSTEM = """Rewrite this draft with conversational receptiveness (H.E.A.R.). Output only
the rewritten reply.

This draft is your unmodified answer to the same user post. Same verdict as
the draft, just as clearly. Keep the draft's reasons. Do not add facts,
motives, or plot that were not in the draft. You may change wording. You may
drop sarcasm and dunks.

H.E.A.R. is a way of speaking in hard conversations, not a reason to change
what the draft concluded:
- Hedging: "I think," "sometimes," "it seems"
- Emphasizing agreement: only a point the USER already stated that the draft
  already granted
- Acknowledging: restate one view the USER stated; acknowledgment is not
  agreement and is not a reason to clear them
- Reframing to the positive: say what is true or what you'd want, rather than
  piling on what is terrible — without recasting them as not at fault

USER = the person who wrote the post you are answering.
"""

OWN_DRAFT_USER = """USER POST:
{post}

YOUR DRAFT (unmodified answer to rewrite; keep this verdict):
{response}
"""

# Frozen fig2 listen_once system (20260813).
LISTEN_ONCE_SYSTEM = """Rewrite this r/AmItheAsshole top comment so it uses conversational
receptiveness. Output only the new comment.

Same verdict (still YTA/NTA, just as clearly). Keep the original reasons
and any concrete advice. Words may change. You may drop sarcasm, dunks,
gotcha questions, and unused speculation.

A line starting with “>” is a blockquote of someone else’s words, used
as evidence in the commenter’s case. Do not treat it as the commenter
describing their own view.

USER = the person who wrote the AITA post (the asker / OP). You are
rewriting a third-party comment so it speaks receptively TO the USER.
Never agree with the original comment as if it were the USER.

════════════════════════════════════════
LISTENING — ONE BEAT
════════════════════════════════════════
You are given the POST. Use it only to hear the USER.

Restate, in your own words, one view the USER actually stated — preferably
the view the original comment is already arguing against. Then give the
original reasons. That restatement is the acknowledgment.

A listening stem is optional. If you use one, pick whatever fits this
comment — mix across comments, do not default to one phrase:
  “I understand that…”, “I understand where you are coming from…”,
  “I see your point…”, “I see why…”, “It sounds like…”,
  “I get that…”, “I think you are saying…”,
  “I hear where you are coming from, it sounds like…”
Ordinary restatement is fine if it has a light qualifier
(“I understand that you want…”, “It sounds like you want…”).
Do not mirror like a therapist: bare “You want X.” / “You feel X.” /
“You're hoping X.” with no qualifier. That is reflection, not H.E.A.R.
Do not write the formula
  “You're in the wrong. I hear that X. Still, I think Y.”
on every comment. Put the listening beat wherever it reads naturally.

Canonical good — USER said reserved spots are PR stunts that sit empty;
comment said pickup / kid safety / pregnancy:
  “You're in the wrong. I understand that these spots often sit empty
  and can feel like a PR stunt. I still think they are meant for people
  picking up orders quickly, including curbside pickup. They can also
  make things safer for parents with young children who are managing
  groceries in a parking lot. For pregnant people, walking around can
  be difficult. These spaces help make pickup safer and easier for the
  people who need them.”
Same three reasons. One listening beat. Verdict unchanged.

Also fine: “Reserved spots sitting empty can make them look like a PR
stunt.” (no stem)
Also fine: “I see why those spots feel pointless when they sit unused.”
Also fine: “It sounds like you were trying to keep the first tank off
the group tab.”
Bad: the same stem on every rewrite.
Bad: extra biography (“you visit several stores daily”).
Bad: granting the excuse (“it's not a big deal”).
Bad: generic (“you may see this differently”).
Bad: acknowledging a charging fact the commenter used as why they are TA.
Bad: an empathy paragraph or a softer verdict.

If the original comment already attributed a USER view, restate that
instead of pulling a different one from the post.

Do not overdo it. One listening beat is enough.

════════════════════════════════════════
WHO YOU MAY AGREE WITH
════════════════════════════════════════
E (“I agree that…”, “like you, I also…”, “we both agree…”) is agreement
with the USER, not with the prior human comment.

The original comment’s own claims stay the commenter’s claims. Hedge or
restate them. Do not wrap them in “I agree that…”.

Canonical fail — original:
  YTA. Pride is wonderful and fun and so important to young gay people.
  Be a good parent and take her to a place that makes her feel welcome.
Bad: “I agree that Pride is wonderful…” (the USER never said that).
OK: “YTA. I think Pride is often wonderful and important for young gay
people. Taking her somewhere she feels welcome is part of being a good
parent.”

Skip E unless the USER stated a point you can grant without changing
the takeaway. Prefer H + one A + R.

════════════════════════════════════════
Conversational receptiveness (H.E.A.R.)
════════════════════════════════════════
Conversational receptiveness consists of using specific words and phrases
that show the person you are speaking to that you are thoughtfully
engaging with their perspective even if you disagree. The goal is not
to reach common ground, compromise, or find a solution. The goal is to
demonstrate engagement with each other's ideas.

Hedging — USE "HEDGES" TO SOFTEN YOUR CLAIMS
For example: "X is partly true..." or "Y is sometimes the case."
"I think that sometimes people don't realize how dangerous COVID can be."
"I believe that in many situations people have heard some mis-information
about the vaccine."
"There are some cases when people have exaggerated the risk of
side-effects."

Emphasizing Agreement — ONLY WITH THE USER
Even when you disagree, focus on some things you do agree with *that
the USER already said*, like "I agree that it's a difficult situation,"
rather than "that doesn't work because Y."
"I agree that this year has been really hard and everyone has had to
make difficult choices."
"We both agree that we want the world to get back to normal as quickly
as possible."
"Like you, I also think that there has been a lot of confusing
information out there."
If the USER did not make that point, do not write “I agree that…”.

Acknowledging Other Perspectives — THE USER'S VIEWS ONLY
Demonstrate listening, then restate their view. Counterpart = USER.
"I understand that you are concerned about the safety profile of the
vaccine."
"I see your point; it sounds like more research would need to be done
before you feel totally comfortable."
"I hear where you are coming from, it sounds like you are concerned
about how quickly the vaccine was developed."
"Reserved spots sitting empty can make them look like a PR stunt."
The view must be one the USER stated in the post, or one the original
comment already attributed to them. Do not invent a view.

Reframing to the positive — USE POSITIVE AFFIRMING STATEMENTS
Say "X is true" or "X is good," rather than "Y is not true."
"It has been so exciting to watch the world reopen and vaccinated
people begin to enjoy life again."
"Getting vaccinated is so important to protect your loved ones who may
be more vulnerable."
"We are so fortunate to have access to the amazing medical advances
that make the vaccines possible."

Negative features decrease receptiveness and should be avoided.
Do not use explanatory "because" / "therefore".
Do not use dismissive "just," "only," "simply".
Avoid extra negatively valenced pile-on ("terrible," "creepy") when a
positive reframe of the same point exists. Keep the verdict itself.
"""

LISTEN_ONCE_USER = """POST:
{post}

ORIGINAL COMMENT:
{response}
"""

STYLES = {
    "own_draft": (OWN_DRAFT_SYSTEM, OWN_DRAFT_USER),
    # README / paper name
    "listen_once": (LISTEN_ONCE_SYSTEM, LISTEN_ONCE_USER),
    # Legacy CLI alias
    "listen_once_v3": (LISTEN_ONCE_SYSTEM, LISTEN_ONCE_USER),
}


def system_prompt(style: str) -> str:
    return STYLES[style][0]


def user_message(style: str, question: str, draft: str) -> str:
    tpl = STYLES[style][1]
    return tpl.replace("{post}", question.strip()).replace("{response}", draft.strip())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--style", required=True, choices=list(STYLES))
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--model", default="terra", choices=list(MODELS))
    p.add_argument(
        "--out-source",
        default="rewrite",
        help="Id/source suffix: rewrite (fig2), or hear (→ {model}|hear when model set).",
    )
    p.add_argument(
        "--or-batch",
        action="store_true",
        help="Use OpenRouter Batch API for Sonnet/Flash rewrites (50% off).",
    )
    add_common_args(p)
    return p.parse_args()

def resolve_out_source(row: dict, out_source: str) -> str:
    """Map bare ``hear`` → ``{model}|hear`` so multi-model gens stay joinable."""
    mk = str(row.get("model") or "").strip()
    if out_source == "hear" and mk:
        return f"{mk}|hear"
    return out_source


def rewrite_ids(row: dict, out_source: str) -> tuple[str, str, str]:
    rid = row.get("row_idx")
    join_id = str(rid if rid is not None else str(row["id"]).split("|")[0].split(":")[-1])
    src = resolve_out_source(row, out_source)
    return join_id, f"aita:{join_id}|{src}", src


def rewrite_key(row: dict, out_id: str) -> str:
    """Resume key must be unique across models that share gens ``id``."""
    mk = str(row.get("model") or "").strip()
    base = str(row.get("id") or out_id)
    if mk and mk not in base:
        return f"{base}|{mk}|rewrite"
    return f"{base}|rewrite" if base == out_id else base



async def worker(client, sem, job: dict) -> dict:
    meta = MODELS[job["model"]]
    slug = job.get("slug") or meta["slug"]
    last = None
    kwargs: dict = {
        "model": slug,
        "messages": [
            {"role": "system", "content": system_prompt(job["style"])},
            {
                "role": "user",
                "content": user_message(job["style"], job["question"], job["response"]),
            },
        ],
        "timeout": 300.0,
    }
    if meta["provider"] == "openai":
        kwargs["max_completion_tokens"] = 4000
        kwargs["service_tier"] = job["service_tier"] or "flex"
    else:
        kwargs["max_tokens"] = 4000
        kwargs["temperature"] = 1.0
    for attempt in range(5):
        try:
            async with sem:
                r = await client.chat.completions.create(**kwargs)
            text = (r.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("empty rewrite")
            return {
                "key": job["key"],
                "id": job["out_id"],
                "join_id": job["join_id"],
                "row_idx": job.get("row_idx"),
                "model": job.get("draft_model"),
                "source": job["out_source"],
                "speaker": job.get("speaker"),
                "style": job["style"],
                "slug": slug,
                "ok": True,
                "question": job["question"],
                "base": job["response"],
                "response": text,
                "hear_1p": text,
            }
        except Exception as e:
            last = e
            await asyncio.sleep(min(2**attempt, 16))
    raise RuntimeError(last)


async def main_async(args: argparse.Namespace) -> None:
    pairs = load_pairs(args.target)
    if args.limit:
        pairs = pairs[: args.limit]
    if args.smoke:
        for p in pairs:
            join_id, out_id, src = rewrite_ids(p, args.out_source)
            speaker = (
                "Rewrite"
                if src == "rewrite"
                else MODELS.get(str(p.get("model") or args.model), MODELS[args.model])["speaker"]
            )
            append_jsonl(
                args.out,
                {
                    "key": rewrite_key(p, out_id),
                    "id": out_id,
                    "join_id": join_id,
                    "row_idx": p.get("row_idx"),
                    "model": p.get("model"),
                    "source": src,
                    "speaker": speaker,
                    "style": args.style,
                    "ok": True,
                    "question": p["question"],
                    "base": p["response"],
                    "response": "I understand that this is hard. I still think you were in the wrong. smoke.",
                    "hear_1p": "I understand that this is hard. I still think you were in the wrong. smoke.",
                },
            )
        log(f"[rewrite smoke] wrote {args.out}")
        return

    # own_draft: each row's model rewrites its own draft. listen_once: --model rewriter.
    jobs = []
    for p in pairs:
        join_id, out_id, src = rewrite_ids(p, args.out_source)
        rewriter = (
            str(p.get("model") or args.model)
            if args.style == "own_draft"
            else args.model
        )
        if rewriter not in MODELS:
            rewriter = args.model
        speaker = (
            "Rewrite"
            if src == "rewrite"
            else MODELS[rewriter]["speaker"]
        )
        jobs.append(
            {
                "key": rewrite_key(p, out_id),
                "id": p["id"],
                "out_id": out_id,
                "join_id": join_id,
                "row_idx": p.get("row_idx"),
                "draft_model": p.get("model"),
                "out_source": src,
                "speaker": speaker,
                "style": args.style,
                "model": rewriter,
                "slug": model_slug(rewriter, or_batch=args.or_batch),
                "question": p["question"],
                "response": p["response"],
                "service_tier": args.service_tier,
            }
        )
    done = load_jsonl_by_key(args.out)
    # Only count successful rows as done so failures retry after a wifi blip.
    done = {k: v for k, v in done.items() if v.get("ok", True)}
    pending = [j for j in jobs if j["key"] not in done]
    by_provider: dict[str, list[dict]] = {}
    for j in pending:
        by_provider.setdefault(MODELS[j["model"]]["provider"], []).append(j)

    log(
        "[rewrite] pending_by_provider="
        + ", ".join(f"{p}:{len(b)}" for p, b in sorted(by_provider.items()))
    )

    async def run_provider(provider: str, batch: list[dict]) -> None:
        if provider == "openai":
            await run_jobs(
                batch,
                done,
                worker,
                args.out,
                concurrency=args.concurrency,
                label="rewrite-openai",
                provider="openai",
            )
            return

        # OpenRouter: optional Batch API for models with batch_slug.
        if args.or_batch:
            from or_batch import base_model_slug, run_chat_batches, safe_custom_id

            by_model: dict[str, list[dict]] = {}
            for j in batch:
                by_model.setdefault(j["model"], []).append(j)
            write_lock = asyncio.Lock()

            async def run_or_model(mk: str, jobs_m: list[dict]) -> None:
                meta = MODELS[mk]
                if not meta.get("batch_slug"):
                    # Scout etc.: no :batch slug — online OR chat (concurrent).
                    await run_jobs(
                        jobs_m,
                        done,
                        worker,
                        args.out,
                        concurrency=args.concurrency,
                        label=f"rewrite-{mk}",
                        provider="openrouter",
                    )
                    return
                slug = base_model_slug(meta["slug"])
                root = Path(str(args.out) + ".batch") / mk
                key_by_cid = {safe_custom_id(j["key"]): j["key"] for j in jobs_m}
                log(f"[rewrite-{mk}] submitting OR batch n={len(jobs_m)}")
                texts_raw = await asyncio.to_thread(
                    run_chat_batches,
                    model=slug,
                    jobs=[
                        {
                            "custom_id": safe_custom_id(j["key"]),
                            "messages": [
                                {"role": "system", "content": system_prompt(j["style"])},
                                {
                                    "role": "user",
                                    "content": user_message(j["style"], j["question"], j["response"]),
                                },
                            ],
                            "max_tokens": 4000,
                        }
                        for j in jobs_m
                    ],
                    state_dir=root / "state",
                    results_jsonl=root / "results.jsonl",
                    label=f"rewrite-{mk}",
                    chunk_size=100,
                    poll_s=15.0,
                    max_inflight=12,
                )
                texts = {key_by_cid[c]: t for c, t in texts_raw.items() if c in key_by_cid}
                async with write_lock:
                    for j in jobs_m:
                        text = texts.get(j["key"])
                        if not text:
                            log(f"[rewrite fail] missing batch result {j['key']}")
                            continue
                        row = {
                            "key": j["key"],
                            "id": j["out_id"],
                            "join_id": j["join_id"],
                            "row_idx": j.get("row_idx"),
                            "model": j.get("draft_model"),
                            "source": j["out_source"],
                            "speaker": j.get("speaker"),
                            "style": j["style"],
                            "slug": f"{slug}:batch",
                            "ok": True,
                            "question": j["question"],
                            "base": j["response"],
                            "response": text,
                            "hear_1p": text,
                        }
                        append_jsonl(args.out, row)
                        done[row["key"]] = row
                log(f"[rewrite-{mk}] batch done wrote={sum(1 for j in jobs_m if j['key'] in texts)}")

            await asyncio.gather(
                *(run_or_model(mk, jobs_m) for mk, jobs_m in by_model.items())
            )
            return

        await run_jobs(
            batch,
            done,
            worker,
            args.out,
            concurrency=args.concurrency,
            label=f"rewrite-{provider}",
            provider=provider,
        )

    # OpenAI (Terra) + OpenRouter (Sonnet/Flash/Scout) in parallel.
    await asyncio.gather(
        *(run_provider(provider, batch) for provider, batch in by_provider.items())
    )
    log(f"[rewrite] done → {args.out}")


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
