#!/usr/bin/env python3
"""WebVoyager evaluator noise-floor analysis.

Three paired comparisons per model, all aligned strictly by task id:
  1. original clean vs new clean        -> WV run-to-run variance on clean app
  2. original logged vs new logged      -> WV run-to-run variance on logged app
  3. new clean vs new logged            -> replicates the clean-vs-logged effect

For each pair: pass counts, rates, diff, 2x2 contingency, agreement/flip rates,
exact McNemar p, and a paired-bootstrap 95% CI for the success-rate difference.
The goal: is the clean-vs-logged gap larger than the evaluator's noise floor?
"""
from __future__ import annotations
import csv, json, math, glob
from pathlib import Path
import numpy as np

WS = Path(__file__).resolve().parent.parent
OUT = WS / "batch_runs" / "paper_materials" / "output"
OUT.mkdir(parents=True, exist_ok=True)
SEED = 20260711
N_BOOT = 20000


def is_success(st: str) -> bool:
    return str(st).upper() == "SUCCESS"


def load_run(root: Path) -> dict:
    """task_id -> status. Join key = task id."""
    out: dict[str, str] = {}
    for ef in glob.glob(str(root / "project_*/webvoyager_results_nolog/*/task*/webvoyager_auto_eval.json")):
        tid = Path(ef).parent.name[len("task"):]
        try:
            out[tid] = str(json.loads(Path(ef).read_text(encoding="utf-8")).get("status", "?"))
        except Exception:
            out[tid] = "EVAL_PARSE_ERROR"
    return out


def exact_binom_two_sided(k: int, n: int, p: float = 0.5) -> float:
    if n == 0:
        return 1.0
    lo = min(k, n - k)
    tail = sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(0, lo + 1))
    return min(1.0, 2.0 * tail)


def paired_bootstrap_diff_ci(pairs: list[tuple[int, int]], seed: int, n_boot: int):
    """pairs: (a_succ, b_succ). Returns (diff_mean, (lo,hi)) for diff = B_rate - A_rate."""
    n = len(pairs)
    if n == 0:
        return 0.0, (0.0, 0.0)
    arr = np.array(pairs, dtype=np.int8)
    a = arr[:, 0].astype(np.float64)
    b = arr[:, 1].astype(np.float64)
    diff_task = b - a
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot = np.array([diff_task[idx[i]].mean() for i in range(n_boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(diff_task.mean()), (float(lo), float(hi))


def compare(label: str, root_a: str, root_b: str) -> dict:
    a = load_run(WS / root_a)
    b = load_run(WS / root_b)
    ids = sorted(set(a) & set(b))
    pairs = [(is_success(a[t]), is_success(b[t])) for t in ids]
    n = len(pairs)
    both_s = sum(1 for x, y in pairs if x and y)
    both_f = sum(1 for x, y in pairs if not x and not y)
    a_only = sum(1 for x, y in pairs if x and not y)
    b_only = sum(1 for x, y in pairs if not x and y)
    a_pass = both_s + a_only
    b_pass = both_s + b_only
    a_rate = a_pass / n if n else 0.0
    b_rate = b_pass / n if n else 0.0
    disc = a_only + b_only
    mcnemar_p = exact_binom_two_sided(a_only, disc, 0.5)
    diff_mean, (ci_lo, ci_hi) = paired_bootstrap_diff_ci(pairs, SEED, N_BOOT)
    return {
        "label": label,
        "n_paired": n,
        "a_pass": a_pass, "a_rate": round(a_rate, 4),
        "b_pass": b_pass, "b_rate": round(b_rate, 4),
        "diff_pp_B_minus_A": round((b_rate - a_rate) * 100, 2),
        "both_success": both_s, "both_fail": both_f,
        "A_only_success": a_only, "B_only_success": b_only,
        "agreement": round((both_s + both_f) / n, 4) if n else 0.0,
        "flip_rate": round(disc / n, 4) if n else 0.0,
        "discordant": disc,
        "exact_mcnemar_p": round(mcnemar_p, 5),
        "diff_ci95_pp": [round(ci_lo * 100, 2), round(ci_hi * 100, 2)],
        "missing_in_A": len(set(b) - set(a)),
        "missing_in_B": len(set(a) - set(b)),
    }


PAIRS = [
    ("Flash | clean app: original vs new (noise floor)", "batch_runs/official/v1_nolog_flash", "batch_runs/official/v1_nolog_flash_rerun2"),
    ("Flash | logged app: original vs new (noise floor)", "batch_runs/official/v1_logged_flash_rerun", "batch_runs/official/v1_logged_flash_rerun2"),
    ("Flash | new clean vs new logged (effect replicate)", "batch_runs/official/v1_nolog_flash_rerun2", "batch_runs/official/v1_logged_flash_rerun2"),
    ("Pro | clean app: original vs new (noise floor)", "batch_runs/official/v1_nolog_pro", "batch_runs/official/v1_nolog_pro_rerun2"),
    ("Pro | logged app: original vs new (noise floor)", "batch_runs/official/v1_logged_pro", "batch_runs/official/v1_logged_pro_rerun2"),
    ("Pro | new clean vs new logged (effect replicate)", "batch_runs/official/v1_nolog_pro_rerun2", "batch_runs/official/v1_logged_pro_rerun2"),
]


def main():
    results = []
    print(f"{'comparison':58} {'A_rate':>7} {'B_rate':>7} {'diffpp':>7} {'agree':>6} {'disc':>5} {'mcnemar_p':>10} {'diffCI95':>16}")
    print("-" * 130)
    for label, a, b in PAIRS:
        r = compare(label, a, b)
        results.append({"A_root": a, "B_root": b, **r})
        print(f"{label:58} {r['a_rate']:>7.4f} {r['b_rate']:>7.4f} {r['diff_pp_B_minus_A']:>+7.2f} "
              f"{r['agreement']:>6.3f} {r['discordant']:>5} {r['exact_mcnemar_p']:>10.4f} "
              f"{str(r['diff_ci95_pp']):>16}")

    (OUT / "v1_noise_floor_analysis.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "v1_noise_floor_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["comparison", "n", "A_pass", "A_rate", "B_pass", "B_rate", "diff_pp(B-A)",
                    "both_succ", "both_fail", "A_only", "B_only", "agreement", "flip_rate",
                    "discordant", "exact_mcnemar_p", "diff_ci95_lo_pp", "diff_ci95_hi_pp",
                    "missing_in_A", "missing_in_B"])
        for r in results:
            w.writerow([r["label"], r["n_paired"], r["a_pass"], r["a_rate"], r["b_pass"], r["b_rate"],
                        r["diff_pp_B_minus_A"], r["both_success"], r["both_fail"], r["A_only_success"],
                        r["B_only_success"], r["agreement"], r["flip_rate"], r["discordant"],
                        r["exact_mcnemar_p"], r["diff_ci95_pp"][0], r["diff_ci95_pp"][1],
                        r["missing_in_A"], r["missing_in_B"]])
    print(f"\nWrote: {OUT}/v1_noise_floor_analysis.json  &  v1_noise_floor_summary.csv")
    print(f"(bootstrap: paired task records, seed={SEED}, {N_BOOT} resamples)")


if __name__ == "__main__":
    main()
