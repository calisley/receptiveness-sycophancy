"""Shared I/O, clients, and job runner for paper scripts."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]


def fill_prompt_template(template: str, **values: str) -> str:
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", val)
    return out


load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
import usage as usage_tracker  # noqa: E402

QUESTION_KEYS = ("question", "prompt", "post", "prompt_1p")
RESPONSE_KEYS = ("response", "advice", "text", "response_1p", "hear_1p")
DEFAULT_JUDGE = "gpt-5.6-luna"
TRAIN_CSV = ROOT / "data/hear/receptive_train.csv"
TRAIN_HEAR = ROOT / "data/hear/hear_v5_signed_scores.jsonl"
AITA_CSV = ROOT / "data/aita/AITA-YTA.csv"

MODELS = {
    "terra": {
        "slug": "gpt-5.6-terra",
        "provider": "openai",
        "source": "terra",
        "speaker": "GPT-5.6 Terra",
    },
    "gpt5": {
        "slug": "gpt-5",
        "provider": "openai",
        "source": "gpt5",
        "speaker": "GPT-5",
    },
    "sonnet5": {
        "slug": "anthropic/claude-sonnet-5",
        "batch_slug": "anthropic/claude-sonnet-5:batch",
        "provider": "openrouter",
        "source": "sonnet5",
        "speaker": "Claude Sonnet 5",
    },
    "gemini_flash": {
        "slug": "google/gemini-3.7-flash",
        "batch_slug": "google/gemini-3.7-flash:batch",
        "provider": "openrouter",
        "source": "gemini_flash",
        "speaker": "Gemini 3.7 Flash",
    },
    "scout": {
        "slug": "meta-llama/llama-4-scout",
        # No :batch variant on OpenRouter; keep standard slug.
        "provider": "openrouter",
        "source": "scout",
        "speaker": "Llama 4 Scout",
    },
}


def model_slug(mk: str, *, or_batch: bool = False) -> str:
    """Resolve generation slug; OR :batch when available and requested."""
    meta = MODELS[mk]
    if or_batch and meta.get("provider") == "openrouter" and meta.get("batch_slug"):
        return str(meta["batch_slug"])
    return str(meta["slug"])


def log(msg: str) -> None:
    print(msg, flush=True)


def pairwise_dummy(share: float, join_id: str = "", source: str = "", other: str = "") -> int:
    return int(share > 0.5)


def strip_proxy() -> None:
    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        os.environ.pop(k, None)


def tracked_client() -> AsyncOpenAI:
    strip_proxy()
    if not isinstance(getattr(usage_tracker, "_run", None), dict):
        usage_tracker._run = {"cost": 0.0}
    usage_tracker._run.setdefault("cost", 0.0)
    return usage_tracker.track(
        AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=2)
    )


def gen_client(provider: str) -> AsyncOpenAI:
    strip_proxy()
    if not isinstance(getattr(usage_tracker, "_run", None), dict):
        usage_tracker._run = {"cost": 0.0}
    usage_tracker._run.setdefault("cost", 0.0)
    if provider == "openai":
        return usage_tracker.track(
            AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=2)
        )
    return usage_tracker.track(
        AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OR_API_KEY"],
            max_retries=2,
            default_headers={
                "HTTP-Referer": "https://github.com/sycophancy-rlhf",
                "X-Title": "sycophancy-rlhf",
            },
        )
    )


def first_text(row: dict, keys: Iterable[str]) -> str:
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in {"nan", "none"}:
            return s
    return ""


def pair_question(row: dict) -> str:
    return first_text(row, QUESTION_KEYS)


def pair_response(row: dict) -> str:
    return first_text(row, RESPONSE_KEYS)


def pair_id(row: dict, fallback: str | None = None) -> str:
    for k in ("id", "key"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    if fallback:
        return fallback
    raise ValueError(f"pair missing id: {list(row)[:12]}")


def normalize_pair(row: dict, *, idx: int = 0) -> dict | None:
    q = pair_question(row)
    a = pair_response(row)
    if not q or not a:
        return None
    out = dict(row)
    pid = pair_id(row, fallback=f"row{idx}")
    out["id"] = pid
    out["question"] = q
    out["response"] = a
    if not str(out.get("join_id") or "").strip():
        if out.get("row_idx") is not None and str(out["row_idx"]) not in {"", "nan"}:
            out["join_id"] = str(int(float(out["row_idx"])))
        else:
            out["join_id"] = pid.split("|", 1)[0]
    return out


def _read_text_lines(path: Path) -> list[str]:
    """Decode text files written as UTF-8 or legacy Windows cp1252."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").splitlines()


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in _read_text_lines(path):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_jsonl_by_key(path: Path, key: str = "key") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in load_jsonl(path):
        k = r.get(key)
        if k is not None:
            out[str(k)] = r
    return out


def append_jsonl(path: Path, row: dict) -> None:
    """Append one JSONL row and fsync so a mid-run wifi drop keeps finished work.

    Uses an advisory flock so parallel dens-A workers can share the same file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        try:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        finally:
            try:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def _looks_like_pair(row: dict) -> bool:
    return bool(pair_question(row) and pair_response(row))


def load_pairs_file(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        import pandas as pd

        df = pd.read_csv(path)
        raw = df.to_dict("records")
    else:
        raw = load_jsonl(path)
    out = []
    for i, row in enumerate(raw):
        row = {k: v for k, v in row.items() if v is None or (not (isinstance(v, float) and v != v))}
        n = normalize_pair(row, idx=i)
        if n:
            out.append(n)
    return out


def load_pairs(path: Path) -> list[dict]:
    if path.is_file():
        return load_pairs_file(path)
    if not path.is_dir():
        raise FileNotFoundError(path)
    named = path / "pairs.jsonl"
    files = (
        [named]
        if named.is_file()
        else sorted(p for p in path.glob("*.jsonl") if p.is_file())
        + sorted(p for p in path.glob("*.csv") if p.is_file())
    )
    if not files:
        raise FileNotFoundError(f"no pair jsonl/csv in {path}")
    out: list[dict] = []
    seen: set[str] = set()
    for f in files:
        try:
            rows = load_pairs_file(f)
        except Exception:
            continue
        if not rows or not _looks_like_pair(rows[0]):
            continue
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append(r)
    if not out:
        raise ValueError(f"no question/response pairs found in {path}")
    return out


def load_aita() -> list[dict]:
    import pandas as pd

    raw = pd.read_csv(AITA_CSV)
    raw = raw.rename(columns={raw.columns[0]: "row_idx"})
    raw["row_idx"] = raw["row_idx"].astype(int)
    rows = []
    for rec in raw.to_dict("records"):
        q = str(rec.get("prompt") or "").strip()
        if not q:
            continue
        rid = int(rec["row_idx"])
        rows.append(
            {
                "id": f"aita_yta:{rid}",
                "row_idx": rid,
                "prompt": q,
                "top_comment": str(rec.get("top_comment") or ""),
            }
        )
    return rows


async def run_jobs(
    jobs: list[dict],
    done: dict[str, dict],
    worker,
    out_path: Path,
    *,
    concurrency: int,
    label: str,
    provider: str = "openai",
) -> tuple[int, int]:
    pending = [j for j in jobs if j["key"] not in done]
    log(f"[{label}] jobs={len(jobs)} done={len(done)} pending={len(pending)}")
    if not pending:
        return 0, 0
    client = gen_client(provider)
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    ok = fail = 0
    q: asyncio.Queue = asyncio.Queue()
    for j in pending:
        q.put_nowait(j)

    async def one(job: dict) -> None:
        nonlocal ok, fail
        try:
            row = await worker(client, sem, job)
        except Exception as e:
            fail += 1
            log(f"[fail] {job.get('key')}: {e}")
            return
        async with lock:
            append_jsonl(out_path, row)
            done[row["key"]] = row
        ok += 1
        if (ok + fail) % 50 == 0:
            cost = float(getattr(usage_tracker, "_run", {}).get("cost", 0) or 0)
            log(f"[{label}] ok={ok} fail={fail} cost=${cost:.3f}")

    async def pump() -> None:
        while True:
            try:
                job = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            await one(job)

    n_workers = max(1, min(concurrency, len(pending)))
    await asyncio.gather(*(pump() for _ in range(n_workers)))
    cost = float(getattr(usage_tracker, "_run", {}).get("cost", 0) or 0)
    log(f"[{label}] finished ok={ok} fail={fail} cost=${cost:.3f}")
    return ok, fail


def fit_hear_ols():
    import pandas as pd
    from sklearn.linear_model import LinearRegression

    from hear import ALL_FEAT

    rows = []
    with TRAIN_HEAR.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if all(k in r for k in ALL_FEAT):
                rows.append({k: float(r[k]) for k in ALL_FEAT} | {"id": int(r["id"])})
    h = pd.DataFrame(rows)
    tr = pd.read_csv(TRAIN_CSV)
    tr["id"] = tr["id"].astype(int)
    m = h.merge(tr[["id", "receptive"]], on="id", how="inner")
    return LinearRegression().fit(
        m[list(ALL_FEAT)].to_numpy(float), m["receptive"].to_numpy(float)
    )


def add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--judge", default=DEFAULT_JUDGE)
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--service-tier", default="flex")
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Write schema-valid dummy rows instead of calling the API.",
    )
