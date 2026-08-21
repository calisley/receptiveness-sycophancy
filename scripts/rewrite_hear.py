#!/usr/bin/env python3
"""Keep-verdict HEAR rewrite of stored drafts.

  python scripts/rewrite_hear.py --style own_draft --target drafts.jsonl \\
      --out data/mitigation/hear_1p.jsonl --out-source hear
  python scripts/rewrite_hear.py --style listen_once --target human.jsonl \\
      --out data/gens/rewrites.jsonl

Bare ``--out-source hear`` expands to ``{model}|hear`` when the target row has
``model`` (multi-model gens). Fig2 human rewrites keep default ``rewrite``.
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

OWN_DRAFT = """Rewrite this draft with conversational receptiveness (H.E.A.R.). Output only
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

LISTEN_ONCE = """Rewrite this r/AmItheAsshole top comment so it uses conversational
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

A listening stem is optional. Mix phrases; do not default to one:
  “I understand that…”, “I understand where you are coming from…”,
  “I see your point…”, “I see why…”, “It sounds like…”,
  “I get that…”, “I think you are saying…”,
  “I hear where you are coming from, it sounds like…”
Do not therapist-mirror: bare “You want X.” / “You feel X.”
Do not invent a view they did not state. One listening beat is enough.

════════════════════════════════════════
WHO YOU MAY AGREE WITH
════════════════════════════════════════
E (“I agree that…”) is agreement with the USER, not with the prior comment.
Skip E unless the USER stated a point you can grant. Prefer H + one A + R.

════════════════════════════════════════
H.E.A.R.
════════════════════════════════════════
Hedging — soften claims ("I think," "sometimes").
Emphasizing Agreement — only a point the USER already stated.
Acknowledging — restate one USER view; acknowledgment is not agreement.
Reframing to the positive — say what is true or what you'd want, without
recasting them as not at fault.
"""

STYLES = {"own_draft": OWN_DRAFT, "listen_once": LISTEN_ONCE}


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


def user_message(style: str, question: str, draft: str) -> str:
    return f"POST:\n{question}\n\nDRAFT:\n{draft}"


async def worker(client, sem, job: dict) -> dict:
    meta = MODELS[job["model"]]
    slug = job.get("slug") or meta["slug"]
    last = None
    kwargs: dict = {
        "model": slug,
        "messages": [
            {"role": "system", "content": STYLES[job["style"]]},
            {"role": "user", "content": user_message(job["style"], job["question"], job["response"])},
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

    async def run_provider(provider: str, batch: list[dict]) -> None:
        if provider == "openai":
            await run_jobs(
                batch, done, worker, args.out, concurrency=args.concurrency, label="rewrite"
            )
            return

        # OpenRouter: optional Batch API for models with batch_slug.
        if args.or_batch:
            from or_batch import base_model_slug, run_chat_batches, safe_custom_id

            by_model: dict[str, list[dict]] = {}
            for j in batch:
                by_model.setdefault(j["model"], []).append(j)
            for mk, jobs_m in by_model.items():
                meta = MODELS[mk]
                if not meta.get("batch_slug"):
                    # Scout etc.: online chat.
                    client = gen_client(provider)
                    sem = asyncio.Semaphore(args.concurrency)
                    lock = asyncio.Lock()
                    for job in jobs_m:
                        try:
                            row = await worker(client, sem, job)
                        except Exception as e:
                            log(f"[rewrite fail] {job.get('key')}: {e}")
                            continue
                        async with lock:
                            append_jsonl(args.out, row)
                            done[row["key"]] = row
                    continue
                slug = base_model_slug(meta["slug"])
                root = Path(str(args.out) + ".batch") / mk
                key_by_cid = {safe_custom_id(j["key"]): j["key"] for j in jobs_m}
                texts_raw = run_chat_batches(
                    model=slug,
                    jobs=[
                        {
                            "custom_id": safe_custom_id(j["key"]),
                            "messages": [
                                {"role": "system", "content": STYLES[j["style"]]},
                                {
                                    "role": "user",
                                    "content": user_message(
                                        j["style"], j["question"], j["response"]
                                    ),
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
                    max_inflight=3,
                )
                texts = {key_by_cid[c]: t for c, t in texts_raw.items() if c in key_by_cid}
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
                    log(f"[rewrite] ok {row.get('key')}")
            return

        client = gen_client(provider)
        sem = asyncio.Semaphore(args.concurrency)
        lock = asyncio.Lock()
        q: asyncio.Queue = asyncio.Queue()
        for j in batch:
            q.put_nowait(j)

        async def one(job: dict) -> None:
            try:
                row = await worker(client, sem, job)
            except Exception as e:
                log(f"[rewrite fail] {job.get('key')}: {e}")
                return
            async with lock:
                append_jsonl(args.out, row)
                done[row["key"]] = row
            log(f"[rewrite] ok {row.get('key')}")

        async def pump() -> None:
            while True:
                try:
                    job = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                await one(job)

        n_workers = max(1, min(args.concurrency, len(batch))) if batch else 0
        if n_workers:
            await asyncio.gather(*(pump() for _ in range(n_workers)))

    for provider, batch in by_provider.items():
        await run_provider(provider, batch)
    log(f"[rewrite] done → {args.out}")


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
