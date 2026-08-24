"""Process-local Luna TPM budget via aiolimiter.

OpenAI org limit is ~2M TPM. Multiple judge processes should split the budget
via ``LUNA_TPM_LIMIT`` (e.g. 900_000 each when two Luna workers run).

Usage::

    from tpm_limit import acquire_luna_tpm, estimate_tokens

    n = estimate_tokens(system + user, max_out=1400)
    await acquire_luna_tpm(n)
    async with sem:
        await client.beta.chat.completions.parse(...)
"""
from __future__ import annotations

import os
from functools import lru_cache

from aiolimiter import AsyncLimiter

# Leave headroom under the hard 2M org cap.
DEFAULT_TPM = int(os.environ.get("LUNA_TPM_LIMIT", "1800000"))


@lru_cache(maxsize=4)
def luna_limiter(tpm: int | None = None) -> AsyncLimiter:
    rate = int(tpm if tpm is not None else DEFAULT_TPM)
    # max_rate tokens per 60s window
    return AsyncLimiter(rate, 60)


def estimate_tokens(
    text: str,
    *,
    max_out: int = 0,
    overhead: int = 200,
    schema_chars: int = 0,
    safety: float = 1.2,
) -> int:
    """Rough char/4 estimate + reserved completion + schema + safety margin."""
    raw = (len(text) // 4) + (schema_chars // 4) + int(max_out) + int(overhead)
    return max(1, int(raw * safety))


async def acquire_luna_tpm(tokens: int, *, tpm: int | None = None) -> None:
    """Block until ``tokens`` fit in the local TPM bucket."""
    rate = int(tpm if tpm is not None else int(os.environ.get("LUNA_TPM_LIMIT", DEFAULT_TPM)))
    lim = luna_limiter(rate)
    left = max(1, int(tokens))
    # aiolimiter forbids amount > max_rate
    cap = int(lim.max_rate)
    while left > 0:
        chunk = min(left, cap)
        await lim.acquire(chunk)
        left -= chunk
