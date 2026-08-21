"""OpenRouter Batch API helpers (50% pricing via /api/beta/batches).

Workflow:
  1. Persist every submitted ``batch_id`` + ``custom_ids`` under ``state_dir``.
  2. On start/resume, sync local state with GET /batches/:id and harvest any
     completed results into ``results_jsonl`` (append + fsync).
  3. Poll open batches until terminal (24h window); do not abandon early.
  4. Only then submit new chunks for still-missing custom_ids.

Re-running the same call is safe after wifi drops or process death.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

from lib import append_jsonl, load_jsonl, log, strip_proxy, write_json

OR_BATCH_URL = "https://openrouter.ai/api/beta/batches"
TERMINAL = frozenset({"completed", "failed", "cancelled", "expired"})


def _headers() -> dict[str, str]:
    strip_proxy()
    key = os.environ.get("OR_API_KEY") or ""
    if not key:
        raise RuntimeError("OR_API_KEY missing")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sycophancy-rlhf",
        "X-Title": "sycophancy-rlhf",
    }


def safe_custom_id(raw: str) -> str:
    """Provider custom_id charset is [A-Za-z0-9_-] only."""
    out = []
    for ch in raw:
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    return s[:240] or "id"


def base_model_slug(slug: str) -> str:
    """Batch API wants the base slug; :batch is listing/pricing only."""
    return slug[:-6] if slug.endswith(":batch") else slug


def _http_json(method: str, url: str, payload: dict | None = None, timeout: float = 120.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(8):
        req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code in {408, 429, 500, 502, 503, 504} and attempt < 7:
                time.sleep(min(2**attempt, 30))
                last = RuntimeError(f"OR batch HTTP {e.code}: {body[:200]}")
                continue
            raise RuntimeError(f"OR batch HTTP {e.code}: {body[:500]}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            log(f"[or-batch] net blip ({type(e).__name__}): {e}; retry {attempt + 1}/8")
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"OR batch network gave up: {last}")


def submit_batch(
    *,
    model: str,
    requests_body: list[dict],
    state_dir: Path,
    label: str,
) -> dict:
    """Submit one batch. ``requests_body`` items: {custom_id, body}."""
    if not requests_body:
        raise ValueError("empty batch")
    model = base_model_slug(model)
    payload = {
        "endpoint": "/v1/chat/completions",
        "model": model,
        "requests": requests_body,
    }
    state_dir.mkdir(parents=True, exist_ok=True)
    created = _http_json("POST", OR_BATCH_URL, payload)
    bid = created.get("id")
    if not bid:
        raise RuntimeError(f"batch submit missing id: {created}")
    meta = {
        "batch_id": bid,
        "label": label,
        "model": model,
        "status": created.get("status", "pending"),
        "custom_ids": [x["custom_id"] for x in requests_body],
        "submitted_at": time.time(),
        "request_counts": created.get("request_counts"),
    }
    write_json(state_dir / f"{bid}.json", meta)
    append_jsonl(
        state_dir / "batches.jsonl",
        {"batch_id": bid, "label": label, "model": model, "n": len(requests_body)},
    )
    log(f"[or-batch] submitted {bid} label={label} n={len(requests_body)} model={model}")
    return meta


def get_batch(batch_id: str, *, retries: int = 8) -> dict:
    """GET batch; retry brief 404s (OR can lag right after submit)."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return _http_json("GET", f"{OR_BATCH_URL}/{batch_id}")
        except RuntimeError as e:
            last = e
            if "404" not in str(e):
                raise
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"batch get gave up on 404 for {batch_id}: {last}")


def _result_text(item: dict) -> str | None:
    """Extract assistant text from an inlined batch result item.

    OpenRouter shape::
      {custom_id, response: {status_code, body: {choices: [{message: {content}}]}}}
    """
    if item.get("error"):
        return None
    resp = item.get("response")
    if not isinstance(resp, dict):
        return None
    if resp.get("status_code") not in (None, 200):
        return None
    body = resp.get("body")
    if not isinstance(body, dict):
        return None
    choices = body.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip() or None


def _write_meta(state_dir: Path, batch_id: str, **updates) -> dict:
    path = state_dir / f"{batch_id}.json"
    meta = json.loads(path.read_text()) if path.is_file() else {"batch_id": batch_id}
    meta.update(updates)
    meta["last_poll"] = time.time()
    write_json(path, meta)
    return meta


def harvest_results(
    batch: dict,
    *,
    results_jsonl: Path,
    already: set[str],
) -> dict[str, str]:
    """Append new result rows from a batch payload; return custom_id → text."""
    out: dict[str, str] = {}
    for item in batch.get("results") or []:
        cid = str(item.get("custom_id") or "")
        if not cid or cid in already:
            continue
        text = _result_text(item)
        row = {
            "custom_id": cid,
            "batch_id": batch.get("id"),
            "ok": bool(text),
            "text": text,
            "error": item.get("error"),
            "status_code": (item.get("response") or {}).get("status_code"),
        }
        append_jsonl(results_jsonl, row)
        already.add(cid)
        if text:
            out[cid] = text
    return out


def sync_batch(
    batch_id: str,
    *,
    state_dir: Path,
    results_jsonl: Path,
    already: set[str],
    stale_abandon_s: float | None = None,
) -> tuple[str, dict[str, str]]:
    """One GET: update local status and harvest if results are present.

    Never locally invents ``abandoned`` while the API still says in_progress —
    Batch has a 24h window and may sit at 0 completed while queued.
    """
    del stale_abandon_s  # kept for call-site compat; unused on purpose
    batch = get_batch(batch_id)
    status = str(batch.get("status") or "unknown")
    counts = batch.get("request_counts") or {}
    got = harvest_results(batch, results_jsonl=results_jsonl, already=already)
    _write_meta(
        state_dir,
        batch_id,
        status=status,
        request_counts=counts,
        finalized_at=batch.get("finalized_at"),
    )
    log(f"[or-batch] sync {batch_id} status={status} counts={counts} harvested={len(got)}")
    return status, got


def poll_batch(
    batch_id: str,
    *,
    results_jsonl: Path,
    state_dir: Path,
    poll_s: float = 15.0,
    already: set[str] | None = None,
    stale_abandon_s: float | None = None,
) -> dict[str, str]:
    """Poll until API terminal status; harvest results as they appear."""
    done = set(already or ())
    out: dict[str, str] = {}
    while True:
        status, got = sync_batch(
            batch_id,
            state_dir=state_dir,
            results_jsonl=results_jsonl,
            already=done,
            stale_abandon_s=stale_abandon_s,
        )
        out.update(got)
        if status in TERMINAL:
            if status != "completed":
                log(f"[or-batch] terminal non-ok {batch_id}: {status}")
            return out
        time.sleep(poll_s)


def load_results(results_jsonl: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in load_jsonl(results_jsonl):
        if r.get("ok") and r.get("custom_id") and r.get("text"):
            out[str(r["custom_id"])] = str(r["text"])
    return out


def list_batch_metas(state_dir: Path) -> list[dict]:
    if not state_dir.is_dir():
        return []
    out = []
    for p in sorted(state_dir.glob("batch-*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out


def open_batch_ids(state_dir: Path) -> list[str]:
    return [
        str(m["batch_id"])
        for m in list_batch_metas(state_dir)
        if m.get("batch_id") and m.get("status") not in TERMINAL
    ]


def run_chat_batches(
    *,
    model: str,
    jobs: Iterable[dict],
    state_dir: Path,
    results_jsonl: Path,
    label: str,
    chunk_size: int = 100,
    poll_s: float = 15.0,
    max_inflight: int = 3,
) -> dict[str, str]:
    """Submit/poll chat jobs via Batch API with durable resume.

    Each job: ``{custom_id, messages, max_tokens?}``.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    job_list = list(jobs)
    have = load_results(results_jsonl)

    # 1) Sync every known batch with the API (harvest completed, abandon zombies).
    for meta in list_batch_metas(state_dir):
        bid = meta.get("batch_id")
        if not bid:
            continue
        if meta.get("status") in TERMINAL and meta.get("status") != "completed":
            continue
        # Always re-sync completed-looking locals too if results missing.
        need = [c for c in (meta.get("custom_ids") or []) if c not in have]
        if meta.get("status") == "completed" and not need:
            continue
        status, got = sync_batch(
            str(bid),
            state_dir=state_dir,
            results_jsonl=results_jsonl,
            already=set(have),
        )
        have.update(got)

    # 2) Work loop: keep ≤max_inflight batches open; poll until all jobs done.
    while True:
        have = load_results(results_jsonl)
        pending = [j for j in job_list if j["custom_id"] not in have]

        owned: set[str] = set()
        for meta in list_batch_metas(state_dir):
            if meta.get("status") in TERMINAL:
                continue
            owned.update(str(x) for x in (meta.get("custom_ids") or []))

        to_submit = [j for j in pending if j["custom_id"] not in owned]
        open_ids = open_batch_ids(state_dir)
        log(
            f"[or-batch] {label}: have={len(have)}/{len(job_list)} "
            f"pending_submit={len(to_submit)} open_batches={len(open_ids)}"
        )

        if not pending:
            return have

        # Fill inflight slots.
        while to_submit and len(open_batch_ids(state_dir)) < max_inflight:
            chunk = to_submit[:chunk_size]
            to_submit = to_submit[chunk_size:]
            reqs = []
            for j in chunk:
                body = {
                    "messages": j["messages"],
                    "max_tokens": int(j.get("max_tokens") or 4000),
                    "temperature": float(j.get("temperature") or 1.0),
                }
                reqs.append({"custom_id": j["custom_id"], "body": body})
            submit_batch(
                model=model,
                requests_body=reqs,
                state_dir=state_dir,
                label=f"{label}:{len(have)}",
            )

        open_ids = open_batch_ids(state_dir)
        if not open_ids:
            if pending:
                raise RuntimeError(
                    f"[or-batch] {label}: {len(pending)} jobs pending but no open batches"
                )
            return have

        progress = False
        for bid in open_ids:
            status, got = sync_batch(
                bid,
                state_dir=state_dir,
                results_jsonl=results_jsonl,
                already=set(have),
            )
            if got:
                have.update(got)
                progress = True
            if status in TERMINAL:
                progress = True
        if not progress:
            time.sleep(poll_s)
