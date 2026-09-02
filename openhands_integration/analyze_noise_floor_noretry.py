#!/usr/bin/env python3
"""Recompute noise-floor results WITHOUT the task-level retry benefit, to match
the paper's methodology (infra-fail / UNKNOWN counted as fail, no rescue).

For each run, tasks that the runner retried (infra-fail in WV round 0) are
forced to FAIL regardless of their post-retry final verdict. Everything else
keeps its final verdict. Then redo the 6 paired comparisons on these no-retry
binary outcomes.
"""
from __future__ import annotations
import csv, json, math, glob, re
from pathlib import Path
import numpy as np

WS = Path(__file__).resolve().parent.parent
OUT = WS / "batch_runs" / "paper_materials" / "output"
SEED = 20260712
N_BOOT = 20000
TASK_RE = re.compile(r"'(\d{6}--\d+)'")


def final_statuses(root: Path) -> dict[str, str]:
    """task_id -> final status (after retry)."""
    out = {}
    for f in glob.glob(str(root / "project_*/webvoyager_results_nolog/*/nolog_v1_summary.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for tid, st in (d.get("tasks") or {}).items():
            out[tid] = str(st)
    return out


def retried_tasks(root: Path) -> set[str]:
    """task_ids that the runner retried (infra-fail in round 0), deduped."""
    retried = set()
    for lg in glob.glob(str(root / "launcher_logs/project_*.log")):
        txt = Path(lg).read_text(encoding="utf-8", errors="ignore")
        for line in txt.splitlines():
            if "Retry round" in line and "infra-failed" in line:
                for m in TASK_RE.findall(line):
                    retried.add(m)
    return retried


def noretry_outcomes(root: Path) -> dict[str, int]:
    """task_id -> 1/0 with retry stripped (retried tasks => 0=fail)."""
    final = final_statuses(root)
    retried = retried_tasks(root)
    return {tid: (1 if (str(st).upper() == "SUCCESS" and tid not in retried) else 0)
            for tid, st in final.items()}


def exact_binom_two_sided(k, n, p=0.5):
    if n == 0: return 1.0
    lo = min(k, n - k)
    return min(1.0, 2.0 * sum(math.comb(n, i) * p**i * (1 - p)**(n - i) for i in range(lo + 1)))


def boot_diff_ci(pairs, seed, n_boot):
    n = len(pairs)
    if n == 0: return 0.0, (0.0, 0.0)
    arr = np.array(pairs, dtype=np.int8)
    diff = arr[:, 1].astype(float) - arr[:, 0].astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot = np.array([diff[idx[i]].mean() for i in range(n_boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(diff.mean()), (float(lo), float(hi))


def compare(label, root_a, root_b):
    a = noretry_outcomes(WS / root_a)
    b = noretry_outcomes(WS / root_b)
    ids = sorted(set(a) & set(b))
    pairs = [(a[t], b[t]) for t in ids]
    n = len(pairs)
    bs = sum(1 for x, y in pairs if x and y)
    bf = sum(1 for x, y in pairs if not x and not y)
    ao = sum(1 for x, y in pairs if x and not y)
    bo = sum(1 for x, y in pairs if not x and y)
    ap, bp = bs + ao, bs + bo
    disc = ao + bo
    diff, (lo, hi) = boot_diff_ci(pairs, SEED, N_BOOT)
    return {
        "label": label, "n": n,
        "A_pass": ap, "A_rate": round(ap / n, 4), "B_pass": bp, "B_rate": round(bp / n, 4),
        "diff_pp": round((bp / n - ap / n) * 100, 2),
        "both_success": bs, "both_fail": bf, "A_only": ao, "B_only": bo,
        "agreement": round((bs + bf) / n, 4), "discordant": disc,
        "mcnemar_p": round(exact_binom_two_sided(ao, disc), 5),
        "diff_ci95_pp": [round(lo * 100, 2), round(hi * 100, 2)],
    }


PAIRS = [
    ("Flash | clean: rerun1 vs rerun2 (noise floor)", "batch_runs/official/v1_nolog_flash", "batch_runs/official/v1_nolog_flash_rerun2"),
    ("Flash | logged: rerun1 vs rerun2 (noise floor)", "batch_runs/official/v1_logged_flash_rerun", "batch_runs/official/v1_logged_flash_rerun2"),
    ("Flash | new clean vs new logged (effect)", "batch_runs/official/v1_nolog_flash_rerun2", "batch_runs/official/v1_logged_flash_rerun2"),
    ("Pro | clean: rerun1 vs rerun2 (noise floor)", "batch_runs/official/v1_nolog_pro", "batch_runs/official/v1_nolog_pro_rerun2"),
    ("Pro | logged: rerun1 vs rerun2 (noise floor)", "batch_runs/official/v1_logged_pro", "batch_runs/official/v1_logged_pro_rerun2"),
    ("Pro | new clean vs new logged (effect)", "batch_runs/official/v1_nolog_pro_rerun2", "batch_runs/official/v1_logged_pro_rerun2"),
]

RUNS = [
    ("Flash clean rerun1", "batch_runs/official/v1_nolog_flash"),
    ("Flash clean rerun2", "batch_runs/official/v1_nolog_flash_rerun2"),
    ("Flash logged rerun1", "batch_runs/official/v1_logged_flash_rerun"),
    ("Flash logged rerun2", "batch_runs/official/v1_logged_flash_rerun2"),
    ("Pro clean rerun1", "batch_runs/official/v1_nolog_pro"),
    ("Pro clean rerun2", "batch_runs/official/v1_nolog_pro_rerun2"),
    ("Pro logged rerun1", "batch_runs/official/v1_logged_pro"),
    ("Pro logged rerun2", "batch_runs/official/v1_logged_pro_rerun2"),
]


def main():
    print("=== 各 run 的率: with-retry vs no-retry (paper 口径) ===")
    print(f"{'run':24} {'with-retry':>12} {'no-retry':>12} {'retried任务':>12}")
    run_noretry = {}
    for label, root in RUNS:
        rootp = WS / root
        fin = final_statuses(rootp)
        retried = retried_tasks(rootp)
        with_rate = sum(1 for s in fin.values() if str(s).upper() == "SUCCESS")
        no_rate = sum(1 for t, s in fin.items() if str(s).upper() == "SUCCESS" and t not in retried)
        tot = len(fin)
        print(f"{label:24} {with_rate}/{tot}={with_rate/tot:.4f}  {no_rate}/{tot}={no_rate/tot:.4f}  {len(retried)}")
        run_noretry[label] = (no_rate, tot)

    print(f"\npaper Flash logged v1 (May, 无任务重试): 399/647 = 0.6167")
    print(f"paper Pro   logged v1 (May, 无任务重试): 420/610 = 0.6889 (96项目/610任务, 口径不同)\n")

    print("=== 6 个配对对比 (no-retry 口径) ===")
    print(f"{'comparison':54} {'A率':>7} {'B率':>7} {'diff':>6} {'agree':>6} {'disc':>5} {'mcnemar':>9} {'CI95':>15}")
    results = []
    for label, a, b in PAIRS:
        r = compare(label, a, b)
        results.append(r)
        print(f"{label:54} {r['A_rate']:.4f} {r['B_rate']:.4f} {r['diff_pp']:+6.2f} {r['agreement']:.4f} {r['discordant']:5} {r['mcnemar_p']:9.4f} [{r['diff_ci95_pp'][0]:+.2f},{r['diff_ci95_pp'][1]:+.2f}]")

    (OUT / "v1_noise_floor_noretry.json").write_text(json.dumps({"run_rates_noretry": run_noretry, "comparisons": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote: {OUT}/v1_noise_floor_noretry.json")


if __name__ == "__main__":
    main()
