#!/usr/bin/env python3
"""Build pairs, rejudge framing with v3 prompt, patch analysis CSVs.

  python scripts/run_framing_v3_rejudge.py --export-only
  python scripts/run_framing_v3_rejudge.py --judge-only
  python scripts/run_framing_v3_rejudge.py --patch-only
  python scripts/run_framing_v3_rejudge.py   # all steps (judge must already be done or run separately)

Never run the judge step in the Cursor sandbox.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ATTIC = ROOT.parent / "sycophancy-rlhf-attic"
OUT = ROOT / "data" / "gens" / "framing_v3"
PAIRS = OUT / "pairs.jsonl"
SCORES = OUT / "framing.jsonl"
sys.path.insert(0, str(ROOT / "src"))
from lib import log  # noqa: E402


def add_pair(
    store: dict[str, dict],
    *,
    corpus: str,
    row_idx: int,
    source: str,
    speaker: str,
    question: str,
    response: str,
) -> None:
    q = (question or "").strip()
    a = (response or "").strip()
    if not q or not a or a.lower() in {"nan", "none"}:
        return
    pid = f"{corpus}:{int(row_idx)}|{source}"
    store[pid] = {
        "id": pid,
        "join_id": str(int(row_idx)),
        "row_idx": int(row_idx),
        "corpus": corpus,
        "source": source,
        "speaker": speaker,
        "question": q,
        "response": a,
    }


def export_pairs() -> list[dict]:
    store: dict[str, dict] = {}

    # --- AITA model / human pairs from attic paper ---
    for name in ("human", "terra", "sonnet5", "gemini_flash", "scout"):
        path = ATTIC / "results/paper/pairs" / f"{name}.jsonl"
        if not path.is_file():
            continue
        with path.open() as f:
            for line in f:
                r = json.loads(line)
                src = str(r.get("source") or name)
                sp = str(r.get("speaker") or src)
                add_pair(
                    store,
                    corpus="aita",
                    row_idx=int(r["row_idx"]),
                    source=src,
                    speaker=sp,
                    question=r.get("question") or "",
                    response=r.get("response") or "",
                )

    # n400 includes gpt5 (map source gpt5 -> gpt-5 to match CSV)
    n400 = ATTIC / "results/paper/pairs/n400_1p_hear.jsonl"
    if n400.is_file():
        with n400.open() as f:
            for line in f:
                r = json.loads(line)
                src = str(r.get("source") or "")
                if src == "gpt5":
                    src = "gpt-5"
                sp = "GPT-5" if src == "gpt-5" else str(r.get("speaker") or src)
                add_pair(
                    store,
                    corpus="aita",
                    row_idx=int(r["row_idx"]),
                    source=src,
                    speaker=sp,
                    question=r.get("question") or "",
                    response=r.get("response") or "",
                )

    # gens.jsonl 1p responses
    for model in ("terra", "sonnet5", "gemini_flash", "scout"):
        path = ATTIC / "results/paper/gens" / model / "gens.jsonl"
        if not path.is_file():
            continue
        with path.open() as f:
            for line in f:
                r = json.loads(line)
                add_pair(
                    store,
                    corpus="aita",
                    row_idx=int(r["row_idx"]),
                    source=model,
                    speaker=str(r.get("speaker") or model),
                    question=r.get("prompt_1p") or r.get("question") or "",
                    response=r.get("response_1p") or r.get("response") or "",
                )

    # Official ELEPHANT AITA-YTA: GPT-5 + Human texts (covers dens)
    aita_path = ATTIC / "data/elephant_official/datasets/AITA-YTA.csv"
    fr_path = (
        ATTIC
        / "data/elephant_official/elephant_full_results/AITA-YTA_full_results.csv"
    )
    if aita_path.is_file() and fr_path.is_file():
        aita = pd.read_csv(aita_path)
        fr = pd.read_csv(fr_path, usecols=["Unnamed: 0", "GPT-5", "Human"])
        m = aita.merge(fr, on="Unnamed: 0")
        for rec in m.to_dict("records"):
            rid = int(rec["Unnamed: 0"])
            post = str(rec.get("prompt") or "")
            add_pair(
                store,
                corpus="aita",
                row_idx=rid,
                source="gpt-5",
                speaker="GPT-5",
                question=post,
                response=str(rec.get("GPT-5") or ""),
            )
            add_pair(
                store,
                corpus="aita",
                row_idx=rid,
                source="human",
                speaker="Human",
                question=post,
                response=str(rec.get("Human") or ""),
            )

    # Fig2 remaining + original 808 rewrites / humans
    for path in (
        ROOT / "data/gens/fig2_remaining/human.jsonl",
        ROOT / "data/gens/fig2_remaining/rewrites.jsonl",
    ):
        if not path.is_file():
            continue
        with path.open() as f:
            for line in f:
                r = json.loads(line)
                src = str(r.get("source") or ("rewrite" if "rewrite" in path.name else "human"))
                sp = str(r.get("speaker") or ("Rewrite" if src == "rewrite" else "Human"))
                add_pair(
                    store,
                    corpus="aita",
                    row_idx=int(r["row_idx"]),
                    source=src,
                    speaker=sp,
                    question=r.get("question") or "",
                    response=r.get("response") or "",
                )

    rw808 = (
        ATTIC
        / "results/paper/fig2_receptivize_human/fig1dens_listen_once_v3_20260813/rewrites.jsonl"
    )
    if rw808.is_file():
        with rw808.open() as f:
            for line in f:
                r = json.loads(line)
                add_pair(
                    store,
                    corpus="aita",
                    row_idx=int(r["row_idx"]),
                    source="rewrite",
                    speaker="Rewrite",
                    question=r.get("prompt") or "",
                    response=r.get("rewrite") or "",
                )

    paired = (
        ATTIC
        / "results/paper/fig2_receptivize_human/fig1dens_listen_once_v3_20260813/paired.csv"
    )
    if paired.is_file():
        pdf = pd.read_csv(paired)
        for rec in pdf.to_dict("records"):
            rid = int(rec["row_idx"])
            post = str(rec.get("post") or "")
            add_pair(
                store,
                corpus="aita",
                row_idx=rid,
                source="human",
                speaker="Human",
                question=post,
                response=str(rec.get("original") or ""),
            )
            if rec.get("rewrite") and not (isinstance(rec.get("rewrite"), float)):
                add_pair(
                    store,
                    corpus="aita",
                    row_idx=rid,
                    source="rewrite",
                    speaker="Rewrite",
                    question=post,
                    response=str(rec.get("rewrite") or ""),
                )

    # OEQ
    for path in (
        ROOT / "data/robustness/oeq/human.jsonl",
        ROOT / "data/robustness/oeq/gpt5.jsonl",
    ):
        if not path.is_file():
            continue
        with path.open() as f:
            for line in f:
                r = json.loads(line)
                add_pair(
                    store,
                    corpus="oeq",
                    row_idx=int(r["row_idx"]),
                    source=str(r.get("source") or ""),
                    speaker=str(r.get("speaker") or r.get("source") or ""),
                    question=r.get("question") or "",
                    response=r.get("response") or "",
                )

    # Restrict to rows that appear in analysis CSVs (plus all OEQ pairs exported)
    needed: set[str] = set()
    for csv_path, corpus_default in (
        (ROOT / "data/aita_sycophancy_scores.csv", "aita"),
        (ROOT / "data/receptiveness_transform.csv", "aita"),
        (ROOT / "data/robustness/oeq/oeq_long.csv", "oeq"),
    ):
        with csv_path.open() as f:
            for r in csv.DictReader(f):
                src = str(r["source"])
                rid = int(r["row_idx"])
                corpus = corpus_default
                needed.add(f"{corpus}:{rid}|{src}")

    rows = [store[k] for k in sorted(store) if k in needed]
    missing = sorted(needed - set(store))
    OUT.mkdir(parents=True, exist_ok=True)
    with PAIRS.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "export_meta.json").write_text(
        json.dumps(
            {
                "n_pairs": len(rows),
                "n_needed": len(needed),
                "n_missing": len(missing),
                "missing_head": missing[:50],
                "by_source": _count_sources(rows),
            },
            indent=2,
        )
        + "\n"
    )
    log(f"[export] wrote {len(rows)} pairs → {PAIRS} (missing {len(missing)}/{len(needed)})")
    if missing:
        log(f"[export] missing head: {missing[:20]}")
    return rows


def _count_sources(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        out[f"{r['corpus']}|{r['source']}"] += 1
    return dict(sorted(out.items()))


def run_judge(*, concurrency: int, service_tier: str, limit: int | None) -> None:
    if not PAIRS.is_file():
        raise SystemExit(f"missing {PAIRS}; run --export-only first")
    cmd = [
        sys.executable,
        str(ROOT / "scripts/judge_elephant.py"),
        "--target",
        str(PAIRS),
        "--out",
        str(SCORES),
        "--metrics",
        "framing",
        "--concurrency",
        str(concurrency),
        "--service-tier",
        service_tier,
    ]
    if limit:
        cmd.extend(["--limit", str(limit)])
    log(f"[judge] {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(ROOT))


def framing_map(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not path.is_file():
        return out
    with path.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("metric") != "framing":
                continue
            if r.get("label") not in (0, 1, 0.0, 1.0, "0", "1"):
                continue
            out[str(r["id"])] = int(float(r["label"]))
    return out


def patch_csv(path: Path, corpus: str, fmap: dict[str, int]) -> dict:
    rows = list(csv.DictReader(path.open()))
    if not rows:
        return {"path": str(path), "n": 0}
    fieldnames = list(rows[0].keys())
    if "framing_v2" not in fieldnames:
        # insert after framing
        i = fieldnames.index("framing") + 1 if "framing" in fieldnames else len(fieldnames)
        fieldnames.insert(i, "framing_v2")
    n_upd = n_same = n_flip = n_miss = 0
    for r in rows:
        pid = f"{corpus}:{int(r['row_idx'])}|{r['source']}"
        old = int(float(r["framing"]))
        r["framing_v2"] = str(old)
        if pid not in fmap:
            n_miss += 1
            continue
        new = fmap[pid]
        if new == old:
            n_same += 1
        else:
            n_flip += 1
        r["framing"] = str(new)
        n_upd += 1
    bak = path.with_suffix(path.suffix + ".pre_framing_v3.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    stats = {
        "path": str(path),
        "n": len(rows),
        "updated": n_upd,
        "same": n_same,
        "flipped": n_flip,
        "missing": n_miss,
        "flip_rate": (n_flip / n_upd) if n_upd else None,
    }
    log(
        f"[patch] {path.name}: updated={n_upd} flip={n_flip} "
        f"({100 * (stats['flip_rate'] or 0):.1f}%) missing={n_miss}"
    )
    return stats


def patch_all() -> None:
    fmap = framing_map(SCORES)
    if not fmap:
        raise SystemExit(f"no framing scores in {SCORES}")
    stats = [
        patch_csv(ROOT / "data/aita_sycophancy_scores.csv", "aita", fmap),
        patch_csv(ROOT / "data/receptiveness_transform.csv", "aita", fmap),
        patch_csv(ROOT / "data/robustness/oeq/oeq_long.csv", "oeq", fmap),
    ]
    (OUT / "patch_stats.json").write_text(json.dumps(stats, indent=2) + "\n")


def sensitivity() -> None:
    """Quick Pearson r and omit-framing check printed to stdout."""
    import math

    def pearson(xs: list[float], ys: list[float]) -> float:
        n = len(xs)
        if n < 3:
            return float("nan")
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        dy = math.sqrt(sum((y - my) ** 2 for y in ys))
        return num / (dx * dy) if dx and dy else float("nan")

    def load(path: Path) -> list[dict]:
        return list(csv.DictReader(path.open()))

    reports = {}
    for label, path, rec_col in (
        ("aita", ROOT / "data/aita_sycophancy_scores.csv", "rec_raw"),
        ("transform", ROOT / "data/receptiveness_transform.csv", "rec_raw"),
        ("oeq", ROOT / "data/robustness/oeq/oeq_long.csv", "rec_raw"),
    ):
        rows = load(path)
        rec = [float(r[rec_col]) for r in rows]
        syc = [
            int(float(r["validation"]))
            + int(float(r["indirectness"]))
            + int(float(r["framing"]))
            + int(float(r["positivity"]))
            for r in rows
        ]
        syc_nof = [
            int(float(r["validation"]))
            + int(float(r["indirectness"]))
            + int(float(r["positivity"]))
            for r in rows
        ]
        if "framing_v2" in rows[0]:
            syc_v2 = [
                int(float(r["validation"]))
                + int(float(r["indirectness"]))
                + int(float(r["framing_v2"]))
                + int(float(r["positivity"]))
                for r in rows
            ]
            flip = sum(
                1
                for r in rows
                if int(float(r["framing"])) != int(float(r["framing_v2"]))
            )
        else:
            syc_v2 = syc
            flip = 0
        reports[label] = {
            "n": len(rows),
            "framing_flip": flip,
            "r_syc_v3": pearson(rec, [float(x) for x in syc]),
            "r_syc_v2": pearson(rec, [float(x) for x in syc_v2]),
            "r_syc_no_framing": pearson(rec, [float(x) for x in syc_nof]),
            "mean_framing_v3": sum(int(float(r["framing"])) for r in rows) / len(rows),
            "mean_framing_v2": (
                sum(int(float(r["framing_v2"])) for r in rows) / len(rows)
                if "framing_v2" in rows[0]
                else None
            ),
        }
    (OUT / "sensitivity.json").write_text(json.dumps(reports, indent=2) + "\n")
    log(json.dumps(reports, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--export-only", action="store_true")
    p.add_argument("--judge-only", action="store_true")
    p.add_argument("--patch-only", action="store_true")
    p.add_argument("--sensitivity-only", action="store_true")
    p.add_argument("--concurrency", type=int, default=96)
    p.add_argument("--service-tier", default="flex")
    p.add_argument("--limit", type=int, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    only = args.export_only or args.judge_only or args.patch_only or args.sensitivity_only
    if args.export_only or not only:
        export_pairs()
    if args.judge_only:
        run_judge(
            concurrency=args.concurrency,
            service_tier=args.service_tier,
            limit=args.limit,
        )
    if args.patch_only:
        patch_all()
        sensitivity()
    if args.sensitivity_only:
        sensitivity()
    if not only:
        log("[main] exported pairs; run --judge-only next (outside sandbox), then --patch-only")


if __name__ == "__main__":
    main()
