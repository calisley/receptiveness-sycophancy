#!/usr/bin/env python3
"""Export ELEPHANT judge prompts -> manuscript/listings/.

Run after any change to scripts/judge_elephant.py:

  python scripts/sync_elephant_listings.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LISTINGS = ROOT / "manuscript" / "listings"


def ascii_for_latex(text: str) -> str:
    repl = {
        "\u2014": "--",
        "\u2013": "-",
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2026": "...",
    }
    for a, b in repl.items():
        text = text.replace(a, b)
    return text


def write_listing(name: str, text: str) -> None:
    LISTINGS.mkdir(parents=True, exist_ok=True)
    (LISTINGS / name).write_text(ascii_for_latex(text).rstrip() + "\n", encoding="utf-8")
    print(f"  {name}")


def elephant_listing(metric: str) -> str:
    from judge_elephant import (  # noqa: E402
        ELEPHANT_SYSTEMS,
        ELEPHANT_TAIL,
        FRAMING_USER_PIN,
        USER_PIN,
        framing_prompt,
        indirectness_prompt,
        validation_prompt,
    )

    fns = {
        "validation": validation_prompt,
        "indirectness": indirectness_prompt,
        "framing": framing_prompt,
    }
    user = fns[metric]("<question>", "<advice>")
    if metric == "validation":
        user_body = user.replace(USER_PIN, "", 1).strip()
        prepend = (
            "--- PREPEND (validation only) ---\n"
            "user_pin.txt (Listing lst:user_pin)\n"
        )
    elif metric == "framing":
        user_body = user.replace(FRAMING_USER_PIN, "", 1).strip()
        prepend = (
            "--- PREPEND (framing only) ---\n"
            "framing_user_pin.txt (Listing lst:framing_user_pin)\n"
        )
    else:
        user_body = user
        prepend = ""
    parts = []
    if prepend:
        parts.append(prepend.rstrip())
    parts.append(f"--- SYSTEM ---\n{ELEPHANT_SYSTEMS[metric].strip()}")
    parts.append(f"--- USER MESSAGE ---\n{user_body}")
    parts.append(f"--- STRUCTURED OUTPUT ---{ELEPHANT_TAIL}")
    return "\n\n".join(parts)


def main() -> None:
    from judge_elephant import FRAMING_USER_PIN, USER_PIN  # noqa: E402

    print("[sync] judge_elephant.py -> manuscript/listings/")
    write_listing("user_pin.txt", USER_PIN.rstrip())
    write_listing("framing_user_pin.txt", FRAMING_USER_PIN.rstrip())
    for metric in ("validation", "indirectness", "framing"):
        write_listing(f"elephant_{metric}.txt", elephant_listing(metric))
    print("[sync] done")


if __name__ == "__main__":
    main()
