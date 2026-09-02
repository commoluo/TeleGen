#!/usr/bin/env python3
"""Rigorous paired analysis: clean v1 vs telemetry-instrumented (logged) v1.

Analyzes EXISTING task-level WebVoyager results only (no reruns). For each model
(DeepSeek-V4-Flash, DeepSeek-V4-Pro) it joins clean vs logged outcomes by task id
and reports paired contingency stats, exact McNemar, paired bootstrap CIs,
Cohen's kappa, project/category breakdowns, and a discordant-task export.

Difference sign convention (per request):  diff = logged_rate - clean_rate.
"""
from __future__ import annotations
import csv, json, math, glob, os
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np

WS = Path(__file__).resolve().parent.parent
DATA = WS / "data" / "test.jsonl"
OUT = WS / "batch_runs" / "paper_materials" / "output"
OUT.mkdir(parents=True, exist_ok=True)

# Contemporaneous, load-matched fresh runs (the only defensible paired source).
SOURCES = {
    "Flash": {
        "clean":  WS / "batch_runs/official/v1_nolog_flash",
        "logged": WS / "batch_runs/official/v1_logged_flash_rerun",
    },
    "Pro": {
        "clean":  WS / "batch_runs/official/v1_nolog_pro",
        "logged": WS / "batch_runs/official/v1_logged_pro",
    },
}
SEED = 20260710
N_BOOT = 20000


def is_success(st: str) -> bool:
    return str(st).upper() == "SUCCESS"


def load_run(root: Path) -> dict:
    """task_id -> {status, reason, eval_path, task_dir, has_interact}. Join key = task_id."""
    out: dict[str, dict] = {}
    for tdir in glob.glob(str(root / "project_*/webvoyager_results_nolog/*/task*")):
        p = Path(tdir)
        if not p.is_dir():
            continue
        tid = p.name[len("task"):]  # e.g. "000022--1"
        ef = p / "webvoyager_auto_eval.json"
        status, reason = "MISSING", ""
        if ef.exists():
            try:
                ev = json.loads(ef.read_text(encoding="utf-8"))
                status = str(ev.get("status", "?"))
                reason = str(ev.get("reason", ""))
            except Exception as exc:
                status, reason = "EVAL_PARSE_ERROR", str(exc)
        out[tid] = {
            "status": status,
            "reason": reason,
            "eval_path": str(ef),
            "task_dir": str(p),
            "has_interact": (p / "interact_messages.json").exists(),
        }
    return out


def load_metadata() -> dict:
    """task_id -> {project_category, task_category, application_type}; also pid -> project_category."""
    pid_cat: dict[str, str] = {}
    task_meta: dict[str, dict] = {}
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line.strip())
            pid = d.get("id")
            pc = (d.get("Category") or {}).get("primary_category", "Unknown")
            pid_cat[pid] = pc
            for idx, it in enumerate(d.get("ui_instruct", [])):
                tid = f"{pid}--{idx + 1}"
                task_meta[tid] = {
                    "project_category": pc,
                    "task_category": (it.get("task_category") or {}).get("primary_category", "Unknown"),
                    "application_type": d.get("application_type", "Unknown"),
                }
    return pid_cat, task_meta


def exact_binom_two_sided(k: int, n: int, p: float = 0.5) -> float:
    """Two-sided exact p for Binomial(n,p): 2 * P(X <= min(k, n-k)), capped at 1."""
    if n == 0:
        return 1.0
    lo = min(k, n - k)
    tail = sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(0, lo + 1))
    return min(1.0, 2.0 * tail)


def asymptotic_mcnemar(b: int, c: int) -> tuple[float, float]:
    """Continuity-corrected chi-square McNemar. Returns (chi2, p)."""
    n = b + c
    if n == 0:
        return 0.0, 1.0
    chi2 = (abs(b - c) - 1) ** 2 / n
    # p for chi2 df=1: p = erfc(sqrt(chi2/2))
    p = math.erfc(math.sqrt(chi2 / 2.0))
    return chi2, p


def cohens_kappa(po: float, clean_rate: float, logged_rate: float) -> float:
    pe = clean_rate * logged_rate + (1 - clean_rate) * (1 - logged_rate)
    if pe >= 1.0:
        return float("nan")
    return (po - pe) / (1 - pe)


def bootstrap_diff_and_agreement(pairs: list[tuple[int, int]], seed: int, n_boot: int):
    """Paired bootstrap over task records. pairs: list of (clean_succ, logged_succ).
    Returns (diff_ci=(lo,hi), agree_ci=(lo,hi), diff_mean, agree_mean, n).
    diff = logged_rate - clean_rate (per request)."""
    n = len(pairs)
    arr = np.array(pairs, dtype=np.int8)  # cols: clean, logged
    clean = arr[:, 0].astype(np.float64)
    logged = arr[:, 1].astype(np.float64)
    diff_task = logged - clean           # per-task signed diff
    agree_task = (clean == logged).astype(np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    # gather is expensive for (20000,647); use take along axis via vectorized indexing
    boot_diff = np.empty(n_boot)
    boot_agree = np.empty(n_boot)
    for i in range(n_boot):
        s = idx[i]
        boot_diff[i] = diff_task[s].mean()
        boot_agree[i] = agree_task[s].mean()
    diff_lo, diff_hi = np.percentile(boot_diff, [2.5, 97.5])
    agree_lo, agree_hi = np.percentile(boot_agree, [2.5, 97.5])
    return (float(diff_lo), float(diff_hi)), (float(agree_lo), float(agree_hi)), \
        float(diff_task.mean()), float(agree_task.mean()), boot_diff


def analyze_model(model: str, task_meta: dict) -> dict:
    clean = load_run(SOURCES[model]["clean"])
    logged = load_run(SOURCES[model]["logged"])
    clean_ids, logged_ids = set(clean), set(logged)

    # ---- alignment diagnostics ----
    dups_clean = [k for k, _ in Counter(_task_ids_from_dirs(SOURCES[model]["clean"])).items() if _ > 1]
    alignment = {
        "clean_task_ids": len(clean_ids),
        "logged_task_ids": len(logged_ids),
        "in_both": len(clean_ids & logged_ids),
        "only_in_clean": sorted(clean_ids - logged_ids),
        "only_in_logged": sorted(logged_ids - clean_ids),
        "duplicate_task_ids_clean": dups_clean,
    }

    paired_ids = sorted(clean_ids & logged_ids)
    pairs = [(is_success(clean[t]["status"]), is_success(logged[t]["status"])) for t in paired_ids]
    n = len(paired_ids)

    both_success = sum(1 for c, l in pairs if c and l)
    both_fail = sum(1 for c, l in pairs if not c and not l)
    clean_only = sum(1 for c, l in pairs if c and not l)          # b: clean=1,logged=0
    logged_only = sum(1 for c, l in pairs if not c and l)         # c: clean=0,logged=1
    clean_pass = both_success + clean_only
    logged_pass = both_success + logged_only

    clean_rate = clean_pass / n if n else 0.0
    logged_rate = logged_pass / n if n else 0.0
    diff_pp = (logged_rate - clean_rate) * 100.0                  # logged - clean
    agreement = (both_success + both_fail) / n if n else 0.0
    flip_rate = (clean_only + logged_only) / n if n else 0.0
    clean_to_fail_rate = clean_only / n if n else 0.0
    fail_to_logged_rate = logged_only / n if n else 0.0
    net_disc = clean_only - logged_only
    ratio = (clean_only / logged_only) if logged_only else float("inf")

    # McNemar (primary: exact binomial over discordant pairs)
    disc = clean_only + logged_only
    mcnemar_exact_p = exact_binom_two_sided(clean_only, disc, 0.5)  # k=clean_only successes among disc
    mcnemar_asym_chi2, mcnemar_asym_p = asymptotic_mcnemar(clean_only, logged_only)

    diff_ci, agree_ci, diff_mean, agree_mean, boot_diff = bootstrap_diff_and_agreement(pairs, SEED, N_BOOT)
    kappa = cohens_kappa(agreement, clean_rate, logged_rate)

    # status distribution (transparency on error treatment)
    clean_status_dist = Counter(clean[t]["status"] for t in paired_ids)
    logged_status_dist = Counter(logged[t]["status"] for t in paired_ids)
    clean_infra_fail = sum(1 for t in paired_ids if not clean[t]["has_interact"])
    logged_infra_fail = sum(1 for t in paired_ids if not logged[t]["has_interact"])

    # ---- breakdowns ----
    def breakdown(keyfn):
        groups: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(paired_ids):
            groups[keyfn(t)].append(i)
        out = {}
        for cat, idxs in sorted(groups.items()):
            pp = [pairs[i] for i in idxs]
            nn = len(pp)
            cp = sum(1 for c, _ in pp if c)
            lp = sum(1 for _, l in pp if l)
            bs = sum(1 for c, l in pp if c and l)
            bf = sum(1 for c, l in pp if not c and not l)
            co = sum(1 for c, l in pp if c and not l)
            lo = sum(1 for c, l in pp if not c and l)
            out[cat] = {
                "n": nn,
                "clean_pass": cp, "logged_pass": lp,
                "clean_rate": round(cp / nn, 4) if nn else 0.0,
                "logged_rate": round(lp / nn, 4) if nn else 0.0,
                "diff_pp": round((lp - cp) / nn * 100, 2) if nn else 0.0,
                "both_success": bs, "both_fail": bf,
                "clean_only_success": co, "logged_only_success": lo,
                "agreement": round((bs + bf) / nn, 4) if nn else 0.0,
                "discordant": co + lo,
            }
        return out

    proj_break = breakdown(lambda t: task_meta.get(t, {}).get("project_category", "Unknown"))
    task_break = breakdown(lambda t: task_meta.get(t, {}).get("task_category", "Unknown"))
    app_break = breakdown(lambda t: task_meta.get(t, {}).get("application_type", "Unknown"))

    # ---- consistency checks ----
    checks = {
        "both_success+clean_only==clean_pass": both_success + clean_only == clean_pass,
        "both_success+logged_only==logged_pass": both_success + logged_only == logged_pass,
        "four_cells_sum==n": (both_success + both_fail + clean_only + logged_only) == n,
        "n_paired": n,
    }

    summary = {
        "model": model,
        "n_paired": n,
        "clean": {"pass": clean_pass, "rate": round(clean_rate, 4)},
        "logged": {"pass": logged_pass, "rate": round(logged_rate, 4)},
        "diff_pp_logged_minus_clean": round(diff_pp, 2),
        "contingency": {
            "both_success": both_success, "both_fail": both_fail,
            "clean_only_success": clean_only, "logged_only_success": logged_only,
        },
        "checks": checks,
        "agreement_rate": round(agreement, 4),
        "flip_rate": round(flip_rate, 4),
        "clean_to_fail_flip_rate": round(clean_to_fail_rate, 4),
        "fail_to_logged_flip_rate": round(fail_to_logged_rate, 4),
        "net_discordant_clean_minus_logged": net_disc,
        "ratio_clean_only_to_logged_only": (round(ratio, 3) if math.isfinite(ratio) else str(ratio)),
        "mcnemar": {
            "discordant_pairs": disc,
            "exact_binomial_p_two_sided": round(mcnemar_exact_p, 5),
            "asymptotic_chi2": round(mcnemar_asym_chi2, 3),
            "asymptotic_p": round(mcnemar_asym_p, 5),
        },
        "bootstrap": {
            "seed": SEED, "resamples": N_BOOT, "unit": "paired_task_records",
            "diff_ci95_logged_minus_clean_pp": [round(diff_ci[0] * 100, 2), round(diff_ci[1] * 100, 2)],
            "agreement_ci95": [round(agree_ci[0], 4), round(agree_ci[1], 4)],
        },
        "cohens_kappa": round(kappa, 4),
        "status_distribution": {
            "clean": dict(clean_status_dist), "logged": dict(logged_status_dist),
        },
        "infra_note": {
            "clean_tasks_missing_interact_messages": clean_infra_fail,
            "logged_tasks_missing_interact_messages": logged_infra_fail,
            "treatment": "Any non-SUCCESS status (NOT_SUCCESS/UNKNOWN/EVAL_ERROR/MISSING/infra-fail) is treated as 0=fail for both conditions.",
        },
        "alignment": alignment,
        "breakdown_project_category": proj_break,
        "breakdown_task_category": task_break,
        "breakdown_application_type": app_break,
    }

    # ---- discordant export rows ----
    disc_rows = []
    for t in paired_ids:
        c, l = is_success(clean[t]["status"]), is_success(logged[t]["status"])
        if c == l:
            continue
        disc_rows.append({
            "model": model,
            "project_id": t.split("--")[0],
            "task_id": t,
            "project_category": task_meta.get(t, {}).get("project_category", ""),
            "task_category": task_meta.get(t, {}).get("task_category", ""),
            "application_type": task_meta.get(t, {}).get("application_type", ""),
            "direction": "clean_only_success" if (c and not l) else "logged_only_success",
            "clean_outcome": clean[t]["status"],
            "logged_outcome": logged[t]["status"],
            "clean_reason": clean[t]["reason"],
            "logged_reason": logged[t]["reason"],
            "clean_has_interact_messages": clean[t]["has_interact"],
            "logged_has_interact_messages": logged[t]["has_interact"],
            "clean_eval_path": clean[t]["eval_path"],
            "logged_eval_path": logged[t]["eval_path"],
        })

    return summary, disc_rows, boot_diff


def _task_ids_from_dirs(root: Path):
    return [Path(p).name[len("task"):] for p in glob.glob(str(root / "project_*/webvoyager_results_nolog/*/task*")) if Path(p).is_dir()]


def main():
    pid_cat, task_meta = load_metadata()
    all_summary = {}
    all_disc = []
    for model in ["Flash", "Pro"]:
        print(f"=== {model} ===")
        s, disc, boot = analyze_model(model, task_meta)
        all_summary[model] = s
        all_disc.extend(disc)
        a = s["alignment"]
        print(f"  clean_ids={a['clean_task_ids']} logged_ids={a['logged_task_ids']} "
              f"paired={a['in_both']} only_clean={len(a['only_in_clean'])} only_logged={len(a['only_in_logged'])}")
        print(f"  clean_rate={s['clean']['rate']} logged_rate={s['logged']['rate']} "
              f"diff(logged-clean)={s['diff_pp_logged_minus_clean']}pp")
        print(f"  both_succ={s['contingency']['both_success']} both_fail={s['contingency']['both_fail']} "
              f"clean_only={s['contingency']['clean_only_success']} logged_only={s['contingency']['logged_only_success']}")
        print(f"  agreement={s['agreement_rate']} mcnemar_exact_p={s['mcnemar']['exact_binomial_p_two_sided']} "
              f"kappa={s['cohens_kappa']}")
        print(f"  diff CI95={s['bootstrap']['diff_ci95_logged_minus_clean_pp']}pp "
              f"agree CI95={s['bootstrap']['agreement_ci95']}")
        print(f"  checks: {s['checks']}")

    # machine-readable outputs
    (OUT / "v1_paired_analysis.json").write_text(json.dumps(all_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "v1_paired_analysis_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["model", "n_paired", "clean_pass", "clean_rate", "logged_pass", "logged_rate",
                    "diff_pp_logged_minus_clean", "both_success", "both_fail", "clean_only_success",
                    "logged_only_success", "agreement_rate", "flip_rate", "net_discordant",
                    "mcnemar_exact_p", "diff_ci95_lo_pp", "diff_ci95_hi_pp", "agreement_ci95_lo",
                    "agreement_ci95_hi", "cohens_kappa"])
        for m, s in all_summary.items():
            w.writerow([m, s["n_paired"], s["clean"]["pass"], s["clean"]["rate"], s["logged"]["pass"],
                        s["logged"]["rate"], s["diff_pp_logged_minus_clean"], s["contingency"]["both_success"],
                        s["contingency"]["both_fail"], s["contingency"]["clean_only_success"],
                        s["contingency"]["logged_only_success"], s["agreement_rate"], s["flip_rate"],
                        s["net_discordant_clean_minus_logged"], s["mcnemar"]["exact_binomial_p_two_sided"],
                        s["bootstrap"]["diff_ci95_logged_minus_clean_pp"][0],
                        s["bootstrap"]["diff_ci95_logged_minus_clean_pp"][1],
                        s["bootstrap"]["agreement_ci95"][0], s["bootstrap"]["agreement_ci95"][1],
                        s["cohens_kappa"]])
    # discordant export
    with (OUT / "v1_paired_discordant_tasks.csv").open("w", newline="", encoding="utf-8") as f:
        if all_disc:
            w = csv.DictWriter(f, fieldnames=list(all_disc[0].keys()))
            w.writeheader()
            w.writerows(all_disc)
    print(f"\nDiscordant tasks exported: {len(all_disc)} -> v1_paired_discordant_tasks.csv")
    print(f"Outputs in: {OUT}")


if __name__ == "__main__":
    main()
