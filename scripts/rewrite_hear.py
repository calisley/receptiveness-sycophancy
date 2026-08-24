#!/usr/bin/env python3
"""Keep-verdict HEAR rewrite of stored drafts.

  python scripts/rewrite_hear.py --style own_draft --target drafts.jsonl \\
      --out data/mitigation/hear_1p.jsonl --out-source hear
  python scripts/rewrite_hear.py --style listen_once_v3 --target human.jsonl \\
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
    fill_prompt_template,
    gen_client,
    load_jsonl,
    load_jsonl_by_key,
    load_pairs,
    load_prompt_parts,
    log,
    model_slug,
    run_jobs,
    tracked_client,
)

# Frozen fig2 prompt (20260813). User turn adds PHRASING hint rotated by row_idx.
LISTEN_ONCE_PHRASING_HINTS = [
    "Restate the USER view with a light qualifier (I understand / it sounds like / I see why). Do not open with bare You want / You feel / You're hoping.",
    "Use 'I understand that' once, then the original reasons.",
    "Use 'I see why' or 'I see your point' once.",
    "Use 'It sounds like' once.",
    "Use 'I get that' or 'I think you are saying' once.",
    "Use 'I understand where you are coming from' or 'I hear where you are coming from, it sounds like'.",
]

STYLE_FILES = {
    "own_draft": "hear_transform_own_draft.txt",
    "listen_once_v3": "receptivize_human_aita_listen_once_v3_20260813.txt",
}

_PROMPT_CACHE: dict[str, tuple[str, str]] = {}


def prompt_parts(style: str) -> tuple[str, str]:
    if style not in _PROMPT_CACHE:
        system, user_tpl = load_prompt_parts(STYLE_FILES[style])
        if not user_tpl:
            raise ValueError(f"prompt file missing USER MESSAGE section: {STYLE_FILES[style]}")
        _PROMPT_CACHE[style] = (system, user_tpl)
    return _PROMPT_CACHE[style]


def system_prompt(style: str) -> str:
    return prompt_parts(style)[0]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--style", required=True, choices=list(STYLE_FILES))
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


def user_message(
    style: str, question: str, draft: str, *, row_idx: int | None = None
) -> str:
    _, tpl = prompt_parts(style)
    q, d = question.strip(), draft.strip()
    if style == "listen_once_v3":
        idx = int(row_idx if row_idx is not None else 0)
        hint = LISTEN_ONCE_PHRASING_HINTS[idx % len(LISTEN_ONCE_PHRASING_HINTS)]
        return fill_prompt_template(tpl, post=q, response=d, phrasing_hint=hint)
    return fill_prompt_template(tpl, post=q, response=d)


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
                "content": user_message(
                    job["style"],
                    job["question"],
                    job["response"],
                    row_idx=job.get("row_idx"),
                ),
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
                                    "content": user_message(
                                        j["style"],
                                        j["question"],
                                        j["response"],
                                        row_idx=j.get("row_idx"),
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
