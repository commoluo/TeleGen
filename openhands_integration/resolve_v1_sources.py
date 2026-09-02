#!/usr/bin/env python3
"""Resolve, for each project, the clean (no-log) v1 source dir and the existing
logged-v1 WebVoyager results dir.

This feeds two consumers:
  * run_v1_webvoyager.py  -> needs the clean v1 source to re-run WebVoyager without logs
  * compare_v1_logged_vs_nolog.py -> needs the logged-v1 task results to compare against

Layout (verified against the official experiment data):
  Flash:  batch_runs/official/flash_llm_injection_data/<data_dir>/project_<id>/
            gen_<id>/project_<id>           <- clean v1 (no logs)
            gen_<id>/project_<id>_LLM       <- instrumented v1 (logged, what WV1 ran on)
            webvoyager_results/<id>/task*   <- logged-v1 WV results
  Pro:    batch_runs/official/pro_llm_injection/project_<id>/
            (same inner layout)

Usage:
    python3 openhands_integration/resolve_v1_sources.py --model flash \
        --start 000001 --end 000101 \
        --output openhands_integration/v1_source_manifest_flash.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


WORKSPACE = Path(__file__).resolve().parent.parent
OFFICIAL = WORKSPACE / "batch_runs" / "official"

# Flash data dirs in priority order (main run first, then retries). Mirrors
# EXPERIMENT_MANIFEST.json -> flash_llm_injection.data_dirs ordering.
FLASH_DATA_DIRS = [
    "multi_docker_full101_20260513_1242",
    "multi_docker_run_20260513_022145",
    "multi_docker_run_20260513_022145_retries",
    "multi_docker_run_20260513_022645",
    "multi_docker_run_20260513_023000",
    "full101_watchdog_20260513_1242",
    "full101_missing8_retry2_20260513_2055",
    "full101_missing20_retry_20260513_1833",
    "full101_missing3_retry3_20260513_2201",
    "watchdog_retries_20260513_022145",
]


def _logged_task_results(results_dir: Path) -> dict:
    """Map task_id -> status for a logged-v1 webvoyager_results/<id> dir."""
    out: dict[str, str] = {}
    if not results_dir.exists():
        return out
    for task_dir in sorted(p for p in results_dir.iterdir() if p.is_dir() and p.name.startswith("task")):
        # task dir name is "task<id>--<n>"; task_id is the part after "task".
        task_id = task_dir.name[len("task"):]
        eval_file = task_dir / "webvoyager_auto_eval.json"
        status = "MISSING_EVAL"
        if eval_file.exists():
            try:
                payload = json.loads(eval_file.read_text(encoding="utf-8"))
                status = str(payload.get("status", "UNKNOWN"))
            except Exception as exc:
                status = f"EVAL_PARSE_ERROR:{exc}"
        out[task_id] = status
    return out


def _is_run_project_dir(path: Path) -> bool:
    """True if this project_<id> dir is a pipeline *run* dir (has WV results or a
    batch_results.json), as opposed to a bare source-code dir living inside a
    gen_<id>/ folder."""
    return (path / "webvoyager_results").is_dir() or (path / "batch_results.json").exists()


def _candidate_project_dirs(model: str, project_id: str) -> list[Path]:
    """All run project_<id> dirs that exist for this model.

    Flash data is scattered across data dirs AND nested attempt subdirs
    (e.g. watchdog_retries/.../000010_attempt2/project_000010), so we search
    recursively. Results are ordered: priority data dirs first (main run before
    retries), then any others; ties keep filesystem order.
    """
    name = f"project_{project_id}"
    if model == "flash":
        base = OFFICIAL / "flash_llm_injection_data"
        priority: list[Path] = []
        others: list[Path] = []
        if base.exists():
            found = {p.resolve() for p in base.rglob(name) if p.is_dir() and _is_run_project_dir(p)}
            # Bucket by priority data dir membership.
            for data_name in FLASH_DATA_DIRS:
                dd = base / data_name
                if not dd.exists():
                    continue
                for p in sorted(found):
                    if dd.resolve() in p.resolve().parents:
                        priority.append(p)
            resolved_priority = {p.resolve() for p in priority}
            others = sorted(p for p in found if p.resolve() not in resolved_priority)
        candidates = priority + others
    elif model == "pro":
        base = OFFICIAL / "pro_llm_injection"
        candidates = [p for p in base.rglob(name) if p.is_dir() and _is_run_project_dir(p)] if base.exists() else []
    else:
        raise ValueError(f"unknown model: {model}")
    # De-duplicate while preserving order.
    seen: set = set()
    unique: list[Path] = []
    for c in candidates:
        r = c.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(c)
    return unique


def _resolve_one(model: str, project_id: str, variant: str = "clean") -> Optional[dict]:
    """Resolve source + logged results for a single project.

    variant:
      "clean"  -> source = project_<id>       (no-log v1, pristine)
      "logged" -> source = project_<id>_LLM   (instrumented v1, with telemetry logs)

    Prefers a project dir that has BOTH the requested source and a non-empty
    logged-v1 results set, so the comparison is always apples-to-apples.
    """
    suffix = "" if variant == "clean" else "_LLM"
    best: Optional[dict] = None
    best_score = (-1, -1)

    for proj_dir in _candidate_project_dirs(model, project_id):
        gen_dir = proj_dir / f"gen_{project_id}"
        source = gen_dir / f"project_{project_id}{suffix}"
        logged_results = proj_dir / "webvoyager_results" / project_id

        if not source.exists():
            continue

        logged_tasks = _logged_task_results(logged_results)
        # Require a real logged baseline to compare against.
        if not logged_tasks:
            continue

        logged_successes = sum(1 for s in logged_tasks.values() if str(s).upper() == "SUCCESS")
        # Score: prefer the attempt with the most SUCCESSFUL tasks (matches the
        # paper's "best result" convention for retried projects), then the most
        # complete (most tasks), then earlier priority order.
        score = (logged_successes, len(logged_tasks))
        if score > best_score:
            best_score = score
            best = {
                "project_id": project_id,
                # Paths are stored RELATIVE to the repo root (WORKSPACE) so the
                # manifest stays machine-portable (no absolute paths committed).
                "project_dir": os.path.relpath(proj_dir, WORKSPACE),
                "clean_source": os.path.relpath(source, WORKSPACE),  # dir to serve (clean or _LLM depending on variant)
                "source_variant": variant,
                "logged_results_dir": os.path.relpath(logged_results, WORKSPACE),
                "logged_task_count": len(logged_tasks),
                "logged_success_count": logged_successes,
            }

    return best


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve clean v1 sources + logged-v1 results per project")
    parser.add_argument("--model", required=True, choices=["flash", "pro"])
    parser.add_argument("--start", default="000001", help="Start project id (inclusive)")
    parser.add_argument("--end", default="000101", help="End project id (inclusive)")
    parser.add_argument("--projects", default=None, help="Explicit comma-separated project ids (overrides start/end)")
    parser.add_argument("--output", required=True, help="Output manifest JSON path")
    parser.add_argument("--variant", default="clean", choices=["clean", "logged"],
                        help="clean = project_<id> (no-log v1); logged = project_<id>_LLM (instrumented v1)")
    args = parser.parse_args()

    if args.projects:
        ids = [p.strip().zfill(6) for p in args.projects.split(",") if p.strip()]
    else:
        ids = [f"{i:06d}" for i in range(int(args.start), int(args.end) + 1)]

    manifest: dict[str, dict] = {}
    missing: list[str] = []
    for pid in ids:
        entry = _resolve_one(args.model, pid, variant=args.variant)
        if entry is None:
            missing.append(pid)
            print(f"[{pid}] MISSING {args.variant} source or logged results", file=sys.stderr)
            continue
        manifest[pid] = entry
        print(f"[{pid}] {args.variant}={Path(entry['clean_source']).name}  logged_tasks={entry['logged_task_count']}")

    payload = {
        "model": args.model,
        "variant": args.variant,
        "workspace": ".",
        "project_count": len(manifest),
        "missing": missing,
        "projects": manifest,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote manifest: {out_path} ({len(manifest)} projects, {len(missing)} missing)")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
