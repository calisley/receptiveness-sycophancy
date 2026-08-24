#!/usr/bin/env python3
"""Schema smoke tests, plus an optional live API pass.

  python scripts/smoke.py           # dummy rows, no API
  python scripts/smoke.py --api     # 1 live 1p+3p per model, then judges;
                                    # also tiny OEQ robustness path
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "data/smoke"
PY = sys.executable
sys.path.insert(0, str(ROOT / "src"))
from lib import MODELS  # noqa: E402

FIG1_COLS = [
    "row_idx",
    "corpus",
    "panel",
    "source",
    "speaker",
    "validation",
    "indirectness",
    "framing",
    "positivity",
    "rec_raw",
]
FIG2_COLS = [
    "row_idx",
    "model",
    "source",
    "speaker",
    "validation",
    "indirectness",
    "framing",
    "positivity",
    "rec_raw",
]
ROBUST_COLS = [
    "row_idx",
    "source",
    "speaker",
    "validation",
    "indirectness",
    "framing",
    "positivity",
    "rec_raw",
]


def run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.check_call(args, cwd=ROOT)


def check_csv(path: Path, cols: list[str]) -> int:
    import pandas as pd

    df = pd.read_csv(path)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"{path} missing {missing}")
    if len(df) == 0:
        raise SystemExit(f"{path} empty")
    return len(df)


def load_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def compile_experiment() -> int:
    """Validate shipped experiment tables (raw Qualtrics exports are not deposited)."""
    shipped = ROOT / "data" / "experiment" / "responses.csv"
    if not shipped.is_file():
        raise SystemExit("missing data/experiment/responses.csv")
    return check_csv(
        shipped,
        [
            "response_id",
            "participant_id",
            "item_id",
            "verdict",
            "quality_human",
            "quality_rewrite",
            "listen_pref_rewrite",
            "advice_pref_rewrite",
            "origin",
            "model_label",
        ],
    )


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def judge_flags(api: bool) -> list[str]:
    return [] if api else ["--smoke"]


def robustness_pipeline(*, api: bool) -> dict[str, int]:
    """Exercise OEQ export → judges → compile (tiny n)."""
    import pandas as pd

    base = SMOKE / "robustness"
    oeq_dir = base / "oeq"
    oeq_dir.mkdir(parents=True, exist_ok=True)

    oeq_csv = oeq_dir / "OEQ_full_results.csv"
    pd.DataFrame(
        [
            {
                "row_idx": 0,
                "prompt": "Smoke OEQ dilemma A: should I tell my friend?",
                "Human": "I understand why you hesitate, but honesty matters here.",
                "GPT-5": "You're right to feel torn; still, telling them is kinder long-term.",
            },
            {
                "row_idx": 1,
                "prompt": "Smoke OEQ dilemma B: workplace ethics.",
                "Human": "Document everything and escalate carefully.",
                "GPT-5": "I hear how stuck you feel; raise it with HR and protect yourself.",
            },
        ]
    ).to_csv(oeq_csv, index=False)

    run(
        [
            PY,
            "scripts/export_elephant_pairs.py",
            "--csv",
            str(oeq_csv),
            "--corpus",
            "oeq",
            "--speakers",
            "human,gpt5",
            "--out-dir",
            str(oeq_dir),
            "--limit",
            "2",
        ]
    )

    flags = judge_flags(api)
    for target, out in (
        (oeq_dir / "human.jsonl", oeq_dir / "elephant.jsonl"),
        (oeq_dir / "gpt5.jsonl", oeq_dir / "elephant.jsonl"),
    ):
        run(
            [
                PY,
                "scripts/judge_elephant.py",
                "--target",
                str(target),
                "--out",
                str(out),
                *flags,
            ]
        )
    for target, out in (
        (oeq_dir / "human.jsonl", oeq_dir / "hear.jsonl"),
        (oeq_dir / "gpt5.jsonl", oeq_dir / "hear.jsonl"),
    ):
        run(
            [
                PY,
                "scripts/judge_hear.py",
                "--target",
                str(target),
                "--out",
                str(out),
                *flags,
            ]
        )
    run(
        [
            PY,
            "scripts/judge_positivity.py",
            "--a",
            str(oeq_dir / "human.jsonl"),
            "--b",
            str(oeq_dir / "gpt5.jsonl"),
            "--out",
            str(oeq_dir / "positivity.jsonl"),
            "--bracket",
            "advice given to someone seeking help",
            *flags,
        ]
    )
    run(
        [
            PY,
            "scripts/compile_robustness.py",
            "--pairs-dir",
            str(oeq_dir),
            "--elephant",
            str(oeq_dir / "elephant.jsonl"),
            "--hear",
            str(oeq_dir / "hear.jsonl"),
            "--positivity",
            str(oeq_dir / "positivity.jsonl"),
            "--out",
            str(oeq_dir / "oeq_long.csv"),
        ]
    )
    n_oeq = check_csv(oeq_dir / "oeq_long.csv", ROBUST_COLS)
    oeq = pd.read_csv(oeq_dir / "oeq_long.csv")
    if set(oeq["speaker"]) < {"Human", "GPT-5"}:
        raise SystemExit(f"oeq_long missing speakers: {sorted(oeq['speaker'].unique())}")
    if oeq["positivity"].isna().any():
        raise SystemExit("oeq_long positivity has NA")

    return {"oeq": n_oeq}



def dummy_pipeline() -> tuple[int, int, int, float]:
    gens = SMOKE / "gens.jsonl"
    run(
        [
            PY,
            "scripts/gen_aita.py",
            "--model",
            "terra",
            "--arm",
            "1p3p",
            "--n",
            "2",
            "--out",
            str(gens),
            "--smoke",
        ]
    )
    rows = load_rows(gens)
    assert rows and "response_1p" in rows[0] and "response_3p" in rows[0], rows[0]
    assert "verdict_1p" in rows[0]

    run(
        [
            PY,
            "scripts/export_pairs.py",
            "--gens",
            str(gens),
            "--source",
            "terra",
            "--speaker",
            "GPT-5.6 Terra",
            "--out-model",
            str(SMOKE / "terra.jsonl"),
            "--out-human",
            str(SMOKE / "human.jsonl"),
        ]
    )
    run(
        [
            PY,
            "scripts/judge_elephant.py",
            "--target",
            str(SMOKE),
            "--out",
            str(SMOKE / "elephant.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_hear.py",
            "--target",
            str(SMOKE / "terra.jsonl"),
            "--out",
            str(SMOKE / "hear.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_hear.py",
            "--target",
            str(SMOKE / "human.jsonl"),
            "--out",
            str(SMOKE / "hear.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_positivity.py",
            "--a",
            str(SMOKE / "human.jsonl"),
            "--b",
            str(SMOKE / "terra.jsonl"),
            "--out",
            str(SMOKE / "positivity.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/compile_fig1.py",
            "--pairs-dir",
            str(SMOKE),
            "--elephant",
            str(SMOKE / "elephant.jsonl"),
            "--positivity",
            str(SMOKE / "positivity.jsonl"),
            "--hear",
            str(SMOKE / "hear.jsonl"),
            "--human-pairs",
            str(SMOKE / "human.jsonl"),
            "--out",
            str(SMOKE / "aita_sycophancy_scores.csv"),
        ]
    )
    n1 = check_csv(SMOKE / "aita_sycophancy_scores.csv", FIG1_COLS)
    run(
        [
            PY,
            "scripts/compile_frontier.py",
            "--gens",
            str(gens),
            "--hear",
            str(SMOKE / "hear.jsonl"),
            "--out",
            str(SMOKE / "frontier.csv"),
        ]
    )
    check_csv(
        SMOKE / "frontier.csv",
        ["model", "row_idx", "rec_raw", "verdict_1p", "verdict_3p"],
    )
    run(
        [
            PY,
            "scripts/rewrite_hear.py",
            "--style",
            "listen_once_v3",
            "--target",
            str(SMOKE / "human.jsonl"),
            "--out",
            str(SMOKE / "rewrites.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_elephant.py",
            "--target",
            str(SMOKE / "rewrites.jsonl"),
            "--out",
            str(SMOKE / "elephant.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_hear.py",
            "--target",
            str(SMOKE / "rewrites.jsonl"),
            "--out",
            str(SMOKE / "hear.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_positivity.py",
            "--a",
            str(SMOKE / "human.jsonl"),
            "--b",
            str(SMOKE / "rewrites.jsonl"),
            "--out",
            str(SMOKE / "pos_fig2.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/compile_fig2.py",
            "--human",
            str(SMOKE / "human.jsonl"),
            "--rewrite",
            str(SMOKE / "rewrites.jsonl"),
            "--elephant",
            str(SMOKE / "elephant.jsonl"),
            "--positivity",
            str(SMOKE / "pos_fig2.jsonl"),
            "--hear",
            str(SMOKE / "hear.jsonl"),
            "--out",
            str(SMOKE / "receptiveness_transform.csv"),
        ]
    )
    n2 = check_csv(SMOKE / "receptiveness_transform.csv", FIG2_COLS)
    run(
        [
            PY,
            "scripts/judge_verdict.py",
            "--target",
            str(gens),
            "--out",
            str(SMOKE / "verdicts.jsonl"),
            "--response-field",
            "response_1p",
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_softness.py",
            "--target",
            str(gens),
            "--out",
            str(SMOKE / "softness.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_substance.py",
            "--target",
            str(SMOKE / "rewrites.jsonl"),
            "--out",
            str(SMOKE / "judged.jsonl"),
            "--smoke",
        ]
    )
    run(
        [
            PY,
            "scripts/compile_mitigation.py",
            "--softness",
            str(SMOKE / "softness.jsonl"),
            "--hear",
            str(SMOKE / "hear.jsonl"),
            "--out",
            str(SMOKE / "transform.csv"),
        ]
    )
    import pandas as pd

    mit = pd.read_csv(SMOKE / "transform.csv")
    free = mit[
        (mit["arm"] == "free")
        & (mit["model_key"] == "terra")
        & mit["landing"].isin(["1p_softer", "3p_softer", "same"])
    ]
    n1p = int((free["landing"] == "1p_softer").sum())
    n0 = int((free["landing"] == "same").sum())
    t = (n1p + 0.5 * n0) / len(free) if len(free) else float("nan")
    n_exp = compile_experiment()
    return n1, n2, n_exp, float(t)


def api_pipeline() -> tuple[int, int, int, float]:
    gens = SMOKE / "gens.jsonl"
    run(
        [
            PY,
            "scripts/gen_aita.py",
            "--model",
            "all",
            "--arm",
            "1p3p",
            "--n",
            "1",
            "--out",
            str(gens),
            "--concurrency",
            "4",
            "--max-tokens",
            "1500",
        ]
    )
    rows = load_rows(gens)
    by_model: dict[str, list[dict]] = {}
    for r in rows:
        by_model.setdefault(str(r.get("model")), []).append(r)
    missing = [mk for mk in MODELS if mk not in by_model]
    if missing:
        raise SystemExit(f"no gens for {missing}")
    for mk, recs in by_model.items():
        ok = [r for r in recs if r.get("ok", True) and r.get("response_1p") and r.get("response_3p")]
        if not ok:
            err = recs[-1].get("error") if recs else None
            raise SystemExit(f"{mk} failed: {err}")
        preview = str(ok[0]["response_1p"]).replace("\n", " ")[:120]
        print(f"[api] {mk} verdict_1p={ok[0].get('verdict_1p')} {preview!r}", flush=True)

    for mk, meta in MODELS.items():
        cmd = [
            PY,
            "scripts/export_pairs.py",
            "--gens",
            str(gens),
            "--source",
            meta["source"],
            "--speaker",
            meta["speaker"],
            "--only-model",
            mk,
            "--keep-verdict",
            "",
            "--out-model",
            str(SMOKE / f"{mk}.jsonl"),
        ]
        if mk == "terra":
            cmd += ["--out-human", str(SMOKE / "human.jsonl")]
        run(cmd)

    human = SMOKE / "human.jsonl"
    if not load_rows(human):
        raise SystemExit("export_pairs wrote no human row")

    elephant = SMOKE / "elephant.jsonl"
    hear = SMOKE / "hear.jsonl"
    positivity = SMOKE / "positivity.jsonl"
    run(
        [
            PY,
            "scripts/judge_elephant.py",
            "--target",
            str(human),
            "--out",
            str(elephant),
            "--concurrency",
            "4",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_hear.py",
            "--target",
            str(human),
            "--out",
            str(hear),
            "--concurrency",
            "4",
        ]
    )
    for mk in MODELS:
        pair = SMOKE / f"{mk}.jsonl"
        run(
            [
                PY,
                "scripts/judge_elephant.py",
                "--target",
                str(pair),
                "--out",
                str(elephant),
                "--concurrency",
                "4",
            ]
        )
        run(
            [
                PY,
                "scripts/judge_hear.py",
                "--target",
                str(pair),
                "--out",
                str(hear),
                "--concurrency",
                "4",
            ]
        )
        run(
            [
                PY,
                "scripts/judge_positivity.py",
                "--a",
                str(human),
                "--b",
                str(pair),
                "--out",
                str(positivity),
                "--concurrency",
                "4",
            ]
        )

    run(
        [
            PY,
            "scripts/compile_fig1.py",
            "--pairs-dir",
            str(SMOKE),
            "--elephant",
            str(elephant),
            "--positivity",
            str(positivity),
            "--hear",
            str(hear),
            "--human-pairs",
            str(human),
            "--out",
            str(SMOKE / "aita_sycophancy_scores.csv"),
        ]
    )
    n1 = check_csv(SMOKE / "aita_sycophancy_scores.csv", FIG1_COLS)
    run(
        [
            PY,
            "scripts/compile_frontier.py",
            "--gens",
            str(gens),
            "--hear",
            str(hear),
            "--out",
            str(SMOKE / "frontier.csv"),
        ]
    )
    check_csv(
        SMOKE / "frontier.csv",
        ["model", "row_idx", "rec_raw", "verdict_1p", "verdict_3p"],
    )

    rewrites = SMOKE / "rewrites.jsonl"
    run(
        [
            PY,
            "scripts/rewrite_hear.py",
            "--style",
            "listen_once_v3",
            "--target",
            str(human),
            "--out",
            str(rewrites),
            "--concurrency",
            "2",
        ]
    )
    if not load_rows(rewrites):
        raise SystemExit("rewrite_hear wrote nothing")
    run(
        [
            PY,
            "scripts/judge_elephant.py",
            "--target",
            str(rewrites),
            "--out",
            str(elephant),
            "--concurrency",
            "4",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_hear.py",
            "--target",
            str(rewrites),
            "--out",
            str(hear),
            "--concurrency",
            "4",
        ]
    )
    pos2 = SMOKE / "pos_fig2.jsonl"
    run(
        [
            PY,
            "scripts/judge_positivity.py",
            "--a",
            str(human),
            "--b",
            str(rewrites),
            "--out",
            str(pos2),
            "--concurrency",
            "4",
        ]
    )
    run(
        [
            PY,
            "scripts/compile_fig2.py",
            "--human",
            str(human),
            "--rewrite",
            str(rewrites),
            "--elephant",
            str(elephant),
            "--positivity",
            str(pos2),
            "--hear",
            str(hear),
            "--out",
            str(SMOKE / "receptiveness_transform.csv"),
        ]
    )
    n2 = check_csv(SMOKE / "receptiveness_transform.csv", FIG2_COLS)
    run(
        [
            PY,
            "scripts/judge_verdict.py",
            "--target",
            str(gens),
            "--out",
            str(SMOKE / "verdicts.jsonl"),
            "--response-field",
            "response_1p",
            "--concurrency",
            "4",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_softness.py",
            "--target",
            str(gens),
            "--out",
            str(SMOKE / "softness.jsonl"),
            "--concurrency",
            "4",
        ]
    )
    run(
        [
            PY,
            "scripts/judge_substance.py",
            "--target",
            str(rewrites),
            "--out",
            str(SMOKE / "judged.jsonl"),
            "--concurrency",
            "4",
        ]
    )
    run(
        [
            PY,
            "scripts/compile_mitigation.py",
            "--softness",
            str(SMOKE / "softness.jsonl"),
            "--hear",
            str(hear),
            "--out",
            str(SMOKE / "transform.csv"),
        ]
    )
    import pandas as pd

    mit = pd.read_csv(SMOKE / "transform.csv")
    if set(mit["model_key"]) < set(MODELS):
        raise SystemExit(f"mitigation missing models: {sorted(mit['model_key'].unique())}")
    free = mit[
        (mit["arm"] == "free")
        & (mit["model_key"] == "terra")
        & mit["landing"].isin(["1p_softer", "3p_softer", "same"])
    ]
    n1p = int((free["landing"] == "1p_softer").sum())
    n0 = int((free["landing"] == "same").sum())
    t = (n1p + 0.5 * n0) / len(free) if len(free) else float("nan")
    n_exp = compile_experiment()
    return n1, n2, n_exp, float(t)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--api",
        action="store_true",
        help="Hit generation and judge APIs (n=1 per model).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if SMOKE.exists():
        shutil.rmtree(SMOKE)
    SMOKE.mkdir(parents=True)
    if not (ROOT / "data/aita/AITA-YTA.csv").is_file():
        raise SystemExit("missing data/aita/AITA-YTA.csv")
    if args.api:
        n1, n2, n_exp, t = api_pipeline()
        rob = robustness_pipeline(api=True)
        print(
            f"smoke --api ok fig1_rows={n1} fig2_rows={n2} exp_rows={n_exp} T={t} "
            f"oeq={rob['oeq']}"
        )
    else:
        n1, n2, n_exp, t = dummy_pipeline()
        rob = robustness_pipeline(api=False)
        print(
            f"smoke ok fig1_rows={n1} fig2_rows={n2} exp_rows={n_exp} T={t} "
            f"oeq={rob['oeq']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
