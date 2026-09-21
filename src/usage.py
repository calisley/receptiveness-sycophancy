"""
usage.py

Token + cost logging for every API-calling step. In a script's build_client(), wrap
the client:  return track(AsyncOpenAI(...)).  Thereafter every chat.completions.create
and beta.chat.completions.parse appends one line to an append-only ledger
(data/usage/log.jsonl, concurrency-safe across the parallel background jobs we run),
prints a per-run summary at exit, and fires a LOUD alert each time CUMULATIVE spend
crosses another $50.

Pricing is per-1M tokens (input, output) from data/usage/pricing.json if present, else
the PLACEHOLDER defaults below. Token counts are always exact; the $ figures are only as
right as these rates — EDIT pricing.json to your real Azure contract rates, or the $50
alerts are meaningless.

CLI:  python src/usage.py report     # print cumulative totals by model
"""

import atexit
import json
import os
import sys
import time

try:
    import fcntl  # POSIX file lock (macOS/Linux) for cross-process alert/dedup
except ImportError:
    fcntl = None

USAGE_DIR = os.environ.get("USAGE_DIR", "data/usage")
LOG = os.path.join(USAGE_DIR, "log.jsonl")
STATE = os.path.join(USAGE_DIR, "state.json")
PRICING_FILE = os.path.join(USAGE_DIR, "pricing.json")
ALERT_EVERY = float(os.environ.get("USAGE_ALERT_EVERY", "50"))
_CHECK_EVERY = 40  # re-check the cumulative threshold every N calls (plus at exit)

# $/1M tokens (input, output). Prefer data/usage/pricing.json when present — keep these
# defaults in sync with it so offline / missing-file estimates still price Scout + gates.
DEFAULT_PRICING = {
    "gpt-5.6-sol": [5.0, 30.0],
    "gpt-5.6-terra": [2.5, 15.0],
    "gpt-5.6-luna": [0.2, 1.2],  # was [1.0, 6.0]; cut to 1/5 (2026-07-31)
    "gpt-5.5": [2.5, 15.0],
    "gpt-5.4": [2.5, 15.0],
    "gpt-5.4-mini": [0.75, 4.5],
    "gpt-5.4-nano": [0.20, 1.25],
    "meta-llama/llama-4-scout": [0.10, 0.30],  # OpenRouter
    "google/gemma-4-26b-a4b-it": [0.07, 0.34],  # OpenRouter; pinned 2026-07-21 (newest Gemma)
    "qwen/qwen3-30b-a3b": [0.10, 0.30],
    "deepseek/deepseek-chat-v3-0324": [0.30, 1.10],
    "_default": [2.5, 15.0],
}

_run = {"calls": 0, "in": 0, "out": 0, "cost": 0.0}


def _pricing():
    if os.path.exists(PRICING_FILE):
        try:
            return {**DEFAULT_PRICING, **json.load(open(PRICING_FILE))}
        except Exception:
            pass
    return DEFAULT_PRICING


def _rate(model):
    P = _pricing()
    if model in P:
        return P[model]
    for k, v in P.items():
        if k != "_default" and k in (model or ""):
            return v
    return P["_default"]


def _append(rec):
    os.makedirs(USAGE_DIR, exist_ok=True)
    with open(LOG, "a") as f:  # O_APPEND writes are atomic for small lines
        f.write(json.dumps(rec) + "\n")


def _cumulative():
    if not os.path.exists(LOG):
        return {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
    tot = {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
    with open(LOG) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            tot["calls"] += 1
            tot["in"] += r.get("in", 0)
            tot["out"] += r.get("out", 0)
            tot["cost"] += r.get("cost", 0.0)
    return tot


_baseline_cost = None  # cumulative ledger cost at first check, scanned ONCE per process


def _check_alert():
    """If cumulative cost crossed a new $ALERT_EVERY boundary, alert once (lock-deduped).

    THROUGHPUT FIX (2026-07-21, gemma k=50 topup postmortem): this used to call
    _cumulative() — a synchronous read+parse of the ENTIRE ledger (158MB / 1.2M lines,
    ~2.3s) — every 40 API calls, INSIDE the caller's asyncio event loop. That alone
    capped any high-concurrency run at ~17 req/s with zero API latency (observed ~6).
    Now we scan the ledger once per process and estimate total = baseline + this run's
    cost. Concurrent processes each undercount the others' in-flight spend, so alerts
    can fire a boundary late — acceptable for a $50-granularity nicety.
    """
    global _baseline_cost
    if _baseline_cost is None:
        _baseline_cost = _cumulative()["cost"] - _run["cost"]
    total = _baseline_cost + _run["cost"]
    os.makedirs(USAGE_DIR, exist_ok=True)
    lf = open(STATE + ".lock", "w")
    try:
        if fcntl:
            fcntl.flock(lf, fcntl.LOCK_EX)
        last = 0.0
        if os.path.exists(STATE):
            try:
                last = json.load(open(STATE)).get("alerted_at", 0.0)
            except Exception:
                pass
        if int(total // ALERT_EVERY) > int(last // ALERT_EVERY):
            boundary = int(total // ALERT_EVERY) * int(ALERT_EVERY)
            print(f"\n{'='*64}\n  \U0001f4b8 SPEND ALERT: cumulative API cost ~${total:,.2f} "
                  f"(crossed ${boundary:,})\n{'='*64}", file=sys.stderr, flush=True)
            json.dump({"alerted_at": total, "ts": time.time()}, open(STATE, "w"))
    finally:
        if fcntl:
            fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()


def record(model, usage, service_tier=None):
    if usage is None:
        return
    pin = getattr(usage, "prompt_tokens", 0) or 0
    pout = getattr(usage, "completion_tokens", 0) or 0
    ri, ro = _rate(model)
    # Found 2026-07-13: this function previously priced every call at flat standard-tier rates
    # regardless of service_tier, overstating tracked cost by ~2x for any Flex call (confirmed:
    # OpenAI actually honors service_tier="flex" and bills accordingly -- verified via a live
    # test call reporting r.service_tier == "flex" -- so the discount is real, not hypothetical).
    # Flex/Batch are both a flat 50% off standard token price. Cached input tokens (automatic,
    # no opt-in) are billed at 10% of the tier's input rate, stacking with the Flex discount.
    tier_mult = 0.5 if service_tier == "flex" else 1.0
    cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    # Reasoning tokens (2026-07-15 billing incident): already INCLUDED in completion_tokens for
    # billing, so cost math is unchanged -- logged separately so a call whose visible answer is
    # one sentence but whose hidden reasoning is 8k tokens is visible in the ledger. Caveat that
    # motivated it: this ledger only ever sees calls that RETURN; billed-but-failed calls
    # (timeouts, cancellations, kills) are invisible, so ledger dollars are a lower bound.
    reasoning = getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
    uncached_pin = max(pin - cached, 0)
    cost = (uncached_pin / 1e6 * ri + cached / 1e6 * ri * 0.1 + pout / 1e6 * ro) * tier_mult
    _run["calls"] += 1
    _run["in"] += pin
    _run["out"] += pout
    _run["cost"] += cost
    _append({"ts": time.time(), "model": model, "in": pin, "out": pout, "cost": round(cost, 6),
              "service_tier": service_tier, "cached": cached, "reasoning": reasoning})
    if _run["calls"] % _CHECK_EVERY == 0:
        _check_alert()


def track(client, default_model=None):
    """Patch a client instance so every completion/parse records token usage."""
    comp = client.chat.completions
    _create = comp.create

    async def create(*a, **k):
        r = await _create(*a, **k)
        record(k.get("model", default_model), getattr(r, "usage", None), getattr(r, "service_tier", None))
        return r
    comp.create = create

    try:
        beta = client.beta.chat.completions
        _parse = beta.parse

        async def parse(*a, **k):
            r = await _parse(*a, **k)
            record(k.get("model", default_model), getattr(r, "usage", None), getattr(r, "service_tier", None))
            return r
        beta.parse = parse
    except Exception:
        pass
    return client


@atexit.register
def _summary():
    if _run["calls"] == 0:
        return
    _check_alert()
    tot = _cumulative()
    print(f"\n[usage] this run: {_run['calls']} calls, {_run['in'] + _run['out']:,} tokens "
          f"(in {_run['in']:,} / out {_run['out']:,}), ~${_run['cost']:.2f}  |  "
          f"cumulative: {tot['calls']:,} calls, ~${tot['cost']:,.2f}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        import collections
        by = collections.defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0})
        tot = _cumulative()
        if os.path.exists(LOG):
            for line in open(LOG):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                b = by[r.get("model", "?")]
                b["calls"] += 1; b["in"] += r.get("in", 0); b["out"] += r.get("out", 0); b["cost"] += r.get("cost", 0.0)
        print(f"Cumulative API usage ({LOG}):")
        for m, b in sorted(by.items(), key=lambda x: -x[1]["cost"]):
            print(f"  {m:16} {b['calls']:>6} calls  {b['in']+b['out']:>12,} tok  ~${b['cost']:,.2f}")
        print(f"  {'TOTAL':16} {tot['calls']:>6} calls  {tot['in']+tot['out']:>12,} tok  ~${tot['cost']:,.2f}")
        print(f"\nPricing ($/1M in,out): {json.dumps(_pricing())}\n(edit {PRICING_FILE} for real rates)")
    else:
        print("usage: python src/usage.py report")
