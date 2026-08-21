#!/usr/bin/env python3
"""Fig-5 dens-A expansion: fresh 1p+3p+HEAR rewrite beyond the frontier panel.

Resume-safe: every stage appends JSONL (fsync) and skips finished keys.
Re-run the same command after a wifi drop; it continues where it left off.

  # Write id lists + dry plan (no API)
  python scripts/run_fig5_dens_a.py --plan

  # Live smoke: 1 new dens post × 4 models (OR :batch for Sonnet/Flash)
  python scripts/run_fig5_dens_a.py --smoke-api

  # Full run (after OR credits). Safe to interrupt / re-run.
  python scripts/run_fig5_dens_a.py --go

Models: terra (OpenAI flex); sonnet5 + gemini_flash (OpenRouter Batch API);
scout (OR standard — no batch variant). Does NOT reuse Fig-1 1p exports.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lib import MODELS, load_jsonl, log, model_slug, write_json  # noqa: E402

OUT = ROOT / "data" / "mitigation" / "dens_a"
SOC = ROOT / "data" / "aita_sycophancy_scores.csv"
FRONTIER = ROOT / "data" / "mitigation" / "frontier.csv"

# Fig-5 dens models (no GPT-5).
MODELS_RUN = ("terra", "sonnet5", "gemini_flash", "scout")
SPEAKER = {mk: MODELS[mk]["speaker"] for mk in MODELS_RUN}
PY = sys.executable


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true", help="Write id files + counts; no API.")
    g.add_argument("--smoke-api", action="store_true", help="1 post/model end-to-end live.")
    g.add_argument("--go", action="store_true", help="Full dens-beyond-panel run.")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--concurrency", type=int, default=4, help="In-flight gens/rewrites.")
    p.add_argument("--judge-concurrency", type=int, default=12)
    p.add_argument(
        "--models",
        nargs="+",
        default=list(MODELS_RUN),
        choices=list(MODELS_RUN),
    )
    p.add_argument("--no-or-batch", action="store_true", help="Disable OR Batch API.")
    p.add_argument(
        "--serial-gen",
        action="store_true",
        help="Run models one-after-another (default: all models in parallel).",
    )
    p.add_argument(
        "--stages",
        nargs="+",
        default=["gen", "rewrite", "hear", "softness"],
        choices=["gen", "rewrite", "hear", "softness", "compile"],
        help="Pipeline stages to run (default through softness).",
    )
    return p.parse_args()


def dens_beyond_panel() -> dict[str, list[int]]:
    soc = pd.read_csv(SOC)
    front = pd.read_csv(FRONTIER)
    out: dict[str, list[int]] = {}
    for mk, sp in SPEAKER.items():
        dens = set(soc.loc[soc.speaker == sp, "row_idx"].astype(int))
        panel = set(front.loc[front.model == sp, "row_idx"].astype(int))
        out[mk] = sorted(dens - panel)
    return out


def write_id_files(base: Path, by_model: dict[str, list[int]], *, n_per: int | None) -> dict[str, Path]:
    ids_dir = base / "ids"
    ids_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for mk, rids in by_model.items():
        take = rids[:n_per] if n_per is not None else rids
        path = ids_dir / f"{mk}.txt"
        path.write_text("".join(f"aita_yta:{i}\n" for i in take))
        paths[mk] = path
        log(f"[ids] {mk}: {len(take)} → {path}")
    return paths


def run(cmd: list[str]) -> None:
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def run_parallel(cmds: list[tuple[str, list[str]]], *, log_dir: Path) -> None:
    """Run labeled commands concurrently; raise if any fails."""
    log_dir.mkdir(parents=True, exist_ok=True)
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONUNBUFFERED": "1"}
    procs: list[tuple[str, subprocess.Popen, Path]] = []
    for label, cmd in cmds:
        log_path = log_dir / f"{label}.log"
        log(f"[parallel] start {label} → {log_path}")
        log(f"$ {' '.join(cmd)}")
        fp = log_path.open("a")
        fp.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        fp.flush()
        p = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=fp,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        procs.append((label, p, log_path))
    failed = []
    for label, p, log_path in procs:
        rc = p.wait()
        log(f"[parallel] done {label} rc={rc} (tail {log_path})")
        if rc != 0:
            failed.append(label)
    if failed:
        raise SystemExit(f"parallel jobs failed: {', '.join(failed)}")


def status(base: Path, models: list[str], id_paths: dict[str, Path]) -> None:
    gens = base / "gens.jsonl"
    by_mk = {mk: 0 for mk in models}
    for r in load_jsonl(gens):
        if r.get("ok") and r.get("model") in by_mk:
            by_mk[str(r["model"])] += 1
    for mk in models:
        want = sum(1 for ln in id_paths[mk].read_text().splitlines() if ln.strip())
        log(f"[status] gens {mk}: {by_mk[mk]}/{want}")
    for name in ("prompt_3p.jsonl", "hear_1p.jsonl", "hear.jsonl", "softness.jsonl"):
        p = base / name
        n = len(load_jsonl(p)) if p.is_file() else 0
        log(f"[status] {name}: {n} lines")


def stage_gen(args: argparse.Namespace, id_paths: dict[str, Path]) -> None:
    out = args.out / "gens.jsonl"
    cache = args.out / "prompt_3p.jsonl"
    or_batch = not args.no_or_batch
    cmds: list[tuple[str, list[str]]] = []
    for mk in args.models:
        cmd = [
            PY,
            "scripts/gen_aita.py",
            "--model",
            mk,
            "--arm",
            "1p3p",
            "--judge-verdicts",
            "--ids-file",
            str(id_paths[mk]),
            "--out",
            str(out),
            "--prompt-3p-cache",
            str(cache),
            "--concurrency",
            str(args.concurrency),
        ]
        if or_batch:
            cmd.append("--or-batch")
        cmds.append((mk, cmd))
        log(f"[gen] queue {mk} slug={model_slug(mk, or_batch=or_batch)}")

    if args.serial_gen:
        for _label, cmd in cmds:
            run(cmd)
        return
    # OpenAI (Terra) and OR models in parallel — separate rate limits.
    run_parallel(cmds, log_dir=args.out / "logs")


def stage_rewrite(args: argparse.Namespace) -> None:
    gens = args.out / "gens.jsonl"
    out = args.out / "hear_1p.jsonl"
    cmd = [
        PY,
        "scripts/rewrite_hear.py",
        "--style",
        "own_draft",
        "--target",
        str(gens),
        "--out",
        str(out),
        "--out-source",
        "hear",
        "--concurrency",
        str(args.concurrency),
        "--service-tier",
        "flex",
    ]
    if not args.no_or_batch:
        cmd.append("--or-batch")
    run(cmd)


def stage_hear(args: argparse.Namespace) -> None:
    """Score free 1p + HEAR rewrite receptiveness (append-only)."""
    gens = args.out / "gens.jsonl"
    rew = args.out / "hear_1p.jsonl"
    # Temporary pair files with response field for load_pairs.
    pairs_base = args.out / "_pairs_base.jsonl"
    pairs_hear = args.out / "_pairs_hear.jsonl"
    if pairs_base.exists():
        pairs_base.unlink()
    if pairs_hear.exists():
        pairs_hear.unlink()
    from lib import append_jsonl

    for g in load_jsonl(gens):
        if not g.get("ok") or not g.get("response_1p"):
            continue
        if g.get("model") not in args.models:
            continue
        append_jsonl(
            pairs_base,
            {
                "id": g["id"],
                "row_idx": g.get("row_idx"),
                "model": g["model"],
                "question": g.get("prompt_1p") or g.get("question"),
                "response": g["response_1p"],
            },
        )
    for r in load_jsonl(rew):
        if not r.get("ok", True):
            continue
        text = r.get("hear_1p") or r.get("response")
        if not text:
            continue
        mk = str(r.get("model") or "")
        if mk not in args.models:
            continue
        append_jsonl(
            pairs_hear,
            {
                "id": r.get("id") or r.get("key"),
                "row_idx": r.get("row_idx"),
                "model": mk,
                "question": r.get("question"),
                "response": text,
                "cond": "hear",
            },
        )
    hear_out = args.out / "hear.jsonl"
    for target in (pairs_base, pairs_hear):
        if not target.is_file() or target.stat().st_size == 0:
            continue
        run(
            [
                PY,
                "scripts/judge_hear.py",
                "--target",
                str(target),
                "--out",
                str(hear_out),
                "--concurrency",
                str(args.judge_concurrency),
                "--service-tier",
                "flex",
            ]
        )


def stage_softness(args: argparse.Namespace) -> None:
    gens = args.out / "gens.jsonl"
    merged = args.out / "gens_with_hear.jsonl"
    run(
        [
            PY,
            "scripts/merge_hear.py",
            "--gens",
            str(gens),
            "--rewrites",
            str(args.out / "hear_1p.jsonl"),
            "--out",
            str(merged),
        ]
    )
    soft = args.out / "softness.jsonl"
    run(
        [
            PY,
            "scripts/judge_softness.py",
            "--target",
            str(merged),
            "--out",
            str(soft),
            "--pair",
            "base_1p_vs_3p",
            "--concurrency",
            str(args.judge_concurrency),
            "--service-tier",
            "flex",
        ]
    )
    # HEAR rewrite vs free 3p (tool arm), when hear_1p present.
    run(
        [
            PY,
            "scripts/judge_softness.py",
            "--target",
            str(merged),
            "--out",
            str(soft),
            "--pair",
            "hear_1p_vs_3p",
            "--response-1p",
            "hear_1p",
            "--response-3p",
            "response_3p",
            "--concurrency",
            str(args.judge_concurrency),
            "--service-tier",
            "flex",
        ]
    )


def stage_compile(args: argparse.Namespace) -> None:
    run(
        [
            PY,
            "scripts/compile_frontier.py",
            "--gens",
            str(args.out / "gens.jsonl"),
            "--hear",
            str(args.out / "hear.jsonl"),
            "--out",
            str(args.out / "frontier_dens_a.csv"),
        ]
    )
    run(
        [
            PY,
            "scripts/compile_mitigation.py",
            "--softness",
            str(args.out / "softness.jsonl"),
            "--hear",
            str(args.out / "hear.jsonl"),
            "--out",
            str(args.out / "transform_dens_a.csv"),
        ]
    )


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    by_model_full = dens_beyond_panel()
    by_model_full = {mk: by_model_full[mk] for mk in args.models}
    # Always keep full id lists on disk (never clobbered by smoke).
    write_id_files(args.out, by_model_full, n_per=None)

    if args.smoke_api:
        work = args.out / "smoke"
        work.mkdir(parents=True, exist_ok=True)
        by_model = {mk: rids[:1] for mk, rids in by_model_full.items()}
        id_paths = write_id_files(work, by_model, n_per=None)
        args.out = work  # stages write under dens_a/smoke/
    else:
        by_model = by_model_full
        id_paths = {mk: args.out / "ids" / f"{mk}.txt" for mk in args.models}

    plan = {
        "mode": "smoke-api" if args.smoke_api else ("plan" if args.plan else "go"),
        "models": {
            mk: {
                "n": len(by_model[mk]),
                "slug": model_slug(mk, or_batch=not args.no_or_batch),
                "ids_file": str(id_paths[mk]),
            }
            for mk in args.models
        },
        "total_gens": sum(len(by_model[mk]) for mk in args.models),
        "or_batch": not args.no_or_batch,
        "out": str(args.out),
        "full_ids": str(args.out.parent / "ids") if args.smoke_api else str(args.out / "ids"),
        "resume": "Re-run the same command; stages skip finished JSONL keys.",
    }
    write_json(args.out / "plan.json", plan)
    log(f"[plan] total gens={plan['total_gens']} → {args.out / 'plan.json'}")
    if args.plan:
        # Status against full run dir (not smoke).
        full = OUT if args.out != OUT else args.out
        # Restore paths for status on full tree when --plan
        full_ids = {mk: OUT / "ids" / f"{mk}.txt" for mk in args.models}
        status(OUT, args.models, full_ids)
        return

    stages = args.stages
    if "gen" in stages:
        stage_gen(args, id_paths)
    if "rewrite" in stages:
        stage_rewrite(args)
    if "hear" in stages:
        stage_hear(args)
    if "softness" in stages:
        stage_softness(args)
    if "compile" in stages:
        stage_compile(args)
    status(args.out, args.models, id_paths)
    log("[dens_a] done (safe to re-run; unfinished keys only)")


if __name__ == "__main__":
    main()
