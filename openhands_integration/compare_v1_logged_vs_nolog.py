#!/usr/bin/env python3
"""Compare the logged-v1 WebVoyager results against the no-log v1 results.

Rebuttal control analysis: does injecting telemetry logs change v1 behavior /
success rate? We pair every (project_id, task_id) across the two conditions and
report aggregate rates, a task-level agreement matrix, per-project deltas, and
the list of flipped tasks. If the two rates match within WebVoyager run-to-run
variance and flips are symmetric, injection does not change behavior.

Inputs:
  --manifest     : v1_source_manifest_<model>.json (gives logged_results_dir per project)
  --nolog-run-root : root holding project_<id>/webvoyager_results_nolog/<id>/ (the new run)
  --model        : flash | pro (labeling)
  --output-prefix : output files are written as <prefix>.{json,csv,md}

Usage:
    python3 openhands_integration/compare_v1_logged_vs_nolog.py \
        --model flash \
        --manifest openhands_integration/v1_source_manifest_flash.json \
        --nolog-run-root batch_runs/official/v1_nolog_flash \
        --output-prefix batch_runs/paper_materials/output/v1_logged_vs_nolog_flash
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent


def _resolve_manifest_path(p: str) -> Path:
    """Resolve a manifest path; relative (new) is anchored at WS, absolute (legacy) kept."""
    pp = Path(p)
    return pp if pp.is_absolute() else WS / pp


def _task_statuses_from_dir(results_dir: Path) -> dict[str, str]:
    """task_id -> status from a webvoyager_results/<id>/ dir (auto_eval.json)."""
    out: dict[str, str] = {}
    if not results_dir.exists():
        return out
    for task_dir in sorted(p for p in results_dir.iterdir() if p.is_dir() and p.name.startswith("task")):
        task_id = task_dir.name[len("task"):]
        eval_file = task_dir / "webvoyager_auto_eval.json"
        status = "MISSING_EVAL"
        if eval_file.exists():
            try:
                status = str(json.loads(eval_file.read_text(encoding="utf-8")).get("status", "UNKNOWN"))
            except Exception:
                status = "EVAL_PARSE_ERROR"
        out[task_id] = status
    return out


def _nolog_statuses(project_id: str, nolog_run_root: Path) -> dict[str, str]:
    """Prefer the runner's nolog_v1_summary.json; fall back to scanning task dirs."""
    proj_dir = nolog_run_root / f"project_{project_id}"
    summary = proj_dir / "webvoyager_results_nolog" / project_id / "nolog_v1_summary.json"
    if summary.exists():
        try:
            payload = json.loads(summary.read_text(encoding="utf-8"))
            tasks = payload.get("tasks") or {}
            if tasks:
                return dict(tasks)
        except Exception:
            pass
    return _task_statuses_from_dir(proj_dir / "webvoyager_results_nolog" / project_id)


def _is_success(status: str) -> bool:
    return str(status).upper() == "SUCCESS"


# Alias: the same helper reads any fresh per-project run-root.
_run_root_statuses = _nolog_statuses


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare logged-v1 vs no-log v1 WebVoyager results")
    parser.add_argument("--model", required=True, choices=["flash", "pro"])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--nolog-run-root", required=True,
                        help="Run-root holding the no-log (clean v1) fresh results")
    parser.add_argument("--logged-run-root", default=None,
                        help="If given, use this fresh run-root as the logged side (contemporaneous "
                             "comparison) instead of the manifest's May logged results")
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    projects = manifest.get("projects") or {}
    nolog_root = Path(args.nolog_run_root).resolve()
    logged_root = Path(args.logged_run_root).resolve() if args.logged_run_root else None
    logged_label = "logged(now)" if logged_root else "logged(May)"

    per_task_rows: list[dict] = []          # one row per (project, task) present in either side
    per_project_rows: list[dict] = []
    flipped: list[dict] = []

    # Paired-task accumulators (tasks present in BOTH conditions) — the only
    # apples-to-apples set, so aggregate rates are always directly comparable.
    both_success = both_fail = logged_only = nolog_only = 0

    for pid in sorted(projects):
        if logged_root is not None:
            logged = _run_root_statuses(pid, logged_root)
        else:
            logged = _task_statuses_from_dir(_resolve_manifest_path(projects[pid]["logged_results_dir"]))
        nolog = _run_root_statuses(pid, nolog_root)

        task_ids = sorted(set(logged) | set(nolog))
        l_ok = n_ok = 0
        for tid in task_ids:
            l_status = logged.get(tid, "ABSENT")
            n_status = nolog.get(tid, "ABSENT")
            l_succ = _is_success(l_status)
            n_succ = _is_success(n_status)
            if l_succ:
                l_ok += 1
            if n_succ:
                n_ok += 1
            per_task_rows.append({
                "project_id": pid, "task_id": tid,
                "logged_status": l_status, "nolog_status": n_status,
                "logged_success": int(l_succ), "nolog_success": int(n_succ),
                "flipped": int(l_succ != n_succ),
            })
            if l_status != "ABSENT" and n_status != "ABSENT":
                if l_succ and n_succ:
                    both_success += 1
                elif not l_succ and not n_succ:
                    both_fail += 1
                elif l_succ and not n_succ:
                    logged_only += 1
                    flipped.append({"project_id": pid, "task_id": tid, "direction": "logged_only_success",
                                    "logged": l_status, "nolog": n_status})
                else:
                    nolog_only += 1
                    flipped.append({"project_id": pid, "task_id": tid, "direction": "nolog_only_success",
                                    "logged": l_status, "nolog": n_status})

        l_rate = round(l_ok / len(task_ids), 4) if task_ids else 0.0
        n_rate = round(n_ok / len(task_ids), 4) if task_ids else 0.0
        per_project_rows.append({
            "project_id": pid,
            "logged_success": l_ok, "nolog_success": n_ok, "num_tasks": len(task_ids),
            "logged_rate": l_rate, "nolog_rate": n_rate,
            "delta_pp": round((n_rate - l_rate) * 100, 2),
        })

    paired_logged_success = both_success + logged_only
    paired_nolog_success = both_success + nolog_only
    paired_total = both_success + both_fail + logged_only + nolog_only
    logged_rate = round(paired_logged_success / paired_total, 4) if paired_total else 0.0
    nolog_rate = round(paired_nolog_success / paired_total, 4) if paired_total else 0.0
    net_flip = nolog_only - logged_only  # nolog-only success (+) vs logged-only success (-)

    summary = {
        "model": args.model,
        "manifest": str(Path(args.manifest).resolve()),
        "nolog_run_root": str(nolog_root),
        "logged_run_root": str(logged_root) if logged_root else None,
        "comparison": f"nolog(now) vs {logged_label}",
        "aggregate": {
            "logged": {"success": paired_logged_success, "total": paired_total, "rate": logged_rate},
            "nolog": {"success": paired_nolog_success, "total": paired_total, "rate": nolog_rate},
            "delta_pp": round((nolog_rate - logged_rate) * 100, 2),
        },
        "agreement_paired": {
            "paired_tasks": paired_total,
            "both_success": both_success,
            "both_fail": both_fail,
            "logged_only_success": logged_only,
            "nolog_only_success": nolog_only,
            "net_flip_nolog_minus_logged": net_flip,
        },
        "projects_with_nolog_results": sum(1 for p in projects if (_nolog_statuses(p, nolog_root))),
        "total_projects_in_manifest": len(projects),
    }

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    # JSON
    (out_prefix.with_suffix(".json")).write_text(
        json.dumps({"summary": summary, "flipped_tasks": flipped}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Per-task CSV
    with (out_prefix.with_suffix(".tasks.csv")).open("w", newline="", encoding="utf-8") as f:
        if per_task_rows:
            w = csv.DictWriter(f, fieldnames=list(per_task_rows[0].keys()))
            w.writeheader()
            w.writerows(per_task_rows)

    # Per-project CSV
    with (out_prefix.with_suffix(".projects.csv")).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["project_id", "logged_success", "nolog_success", "num_tasks",
                                          "logged_rate", "nolog_rate", "delta_pp"])
        w.writeheader()
        w.writerows(per_project_rows)

    # Markdown report
    md = []
    md.append(f"# v1 logged vs no-log — {args.model}\n")
    md.append("Rebuttal control: does LLM telemetry injection change v1 WebVoyager success rate?\n")
    md.append(f"\n_Comparison: nolog(now) vs **{logged_label}**_.\n")
    md.append("\n## Aggregate\n")
    md.append("| condition | success | total | rate |")
    md.append("|---|---|---|---|")
    md.append(f"| logged v1 (instrumented) | {paired_logged_success} | {paired_total} | {logged_rate:.4f} |")
    md.append(f"| no-log v1 (clean)        | {paired_nolog_success} | {paired_total} | {nolog_rate:.4f} |")
    md.append(f"\n**Δ (nolog − logged) = {summary['aggregate']['delta_pp']:+.2f} pp**\n")
    md.append("\n## Task-level agreement (paired tasks, present in both)\n")
    md.append("| both success | both fail | logged-only success | no-log-only success | net flip |")
    md.append("|---|---|---|---|---|")
    md.append(f"| {both_success} | {both_fail} | {logged_only} | {nolog_only} | {net_flip:+d} |")
    md.append(f"\n_Paired tasks: {paired_total}. Projects in manifest: {len(projects)}; with no-log results: {summary['projects_with_nolog_results']}._\n")
    if flipped:
        md.append(f"\n## Flipped tasks ({len(flipped)})\n")
        md.append("| project | task | direction | logged | no-log |")
        md.append("|---|---|---|---|---|")
        for fl in flipped[:200]:
            md.append(f"| {fl['project_id']} | {fl['task_id']} | {fl['direction']} | {fl['logged']} | {fl['nolog']} |")
        if len(flipped) > 200:
            md.append(f"\n_...and {len(flipped) - 200} more (see .json)_")
    (out_prefix.with_suffix(".md")).write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"Wrote: {out_prefix}.{{json,tasks.csv,projects.csv,md}}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
