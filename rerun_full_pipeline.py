#!/usr/bin/env python3
"""
Re-run the complete LLM-inject pipeline for both runs:
  Step 1: Re-run WV v1 with qwen3.5-plus on the log-injected code
  Step 2: Run optimize_batch_results.py (Phase1 telemetry brief + Phase2 OH repair + Phase3 WV v2)

Background: previous WV v1 runs used qwen-vl-max which returned 400 Bad Request errors.
Previous Phase 2 runs got no_llm_calls (OH was also misconfigured).
Both issues are now fixed. This script re-runs everything from WV v1 onward.

Usage:
    cd /Users/luoyujia/Downloads/Fullstack-WebGen
    conda activate base
    python3 rerun_full_pipeline.py [--run RUN_NAME] [--start 000001] [--end 000043]
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Add openhands_integration to path so we can import pipeline modules
sys.path.insert(0, str(Path(__file__).parent / "openhands_integration"))

from dotenv import load_dotenv
from model_config import apply_unified_model, normalize_model_name

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

from dynamic_repair_pipeline import PipelinePaths, build_paths, phase3_webvoyager_test

DEFAULT_RUNS = [
    "run_20260418_115444",
    "run_20260419_051444",
]


def _discover_project_ids(run_dir: Path) -> list:
    ids = sorted([
        p.name.replace("gen_", "")
        for p in run_dir.iterdir()
        if p.is_dir() and p.name.startswith("gen_") and len(p.name) > 4
    ])
    return ids


def _resolve_source_workspace(run_dir: Path, project_id: str, source_variant: str) -> Path:
    suffix = ""
    variant = (source_variant or "default").strip().lower()
    if variant == "ast":
        suffix = "_AST"
    elif variant == "llm":
        suffix = "_LLM"
    return run_dir / f"gen_{project_id}" / f"project_{project_id}{suffix}"


def _prepare_wv_experiment_workspace(source_workspace: Path) -> Path:
    experiment_workspace = source_workspace.parent / f"{source_workspace.name}_wv_experiment"
    if experiment_workspace.exists():
        shutil.rmtree(experiment_workspace)
    shutil.copytree(
        source_workspace,
        experiment_workspace,
        ignore=shutil.ignore_patterns("node_modules", ".git", "__pycache__"),
        symlinks=True,
    )
    return experiment_workspace


def rerun_wv1_for_run(
    run_dir: Path,
    project_ids: list,
    source_variant: str = "default",
    results_subdir: str = "webvoyager_results",
):
    """Re-run WebVoyager v1 on the log-injected source code for all projects."""
    print(f"\n{'='*60}")
    print(f"[WV v1] Re-running on: {run_dir.name}")
    print(f"[WV v1] Projects: {len(project_ids)}")
    print(f"[WV v1] Source variant: {source_variant}")
    print(f"[WV v1] Results subdir: {results_subdir}")
    print(f"[WV v1] Model: {os.getenv('WEBVOYAGER_MODEL', 'qwen3.5-plus')}")
    print(f"{'='*60}\n")

    success = 0
    failed = 0

    for i, pid in enumerate(project_ids, 1):
        source_workspace = _resolve_source_workspace(run_dir, pid, source_variant)
        wv_results_dir = run_dir / results_subdir / pid

        print(f"  [{i}/{len(project_ids)}] {pid} ...", end=" ", flush=True)

        if not source_workspace.exists():
            print(f"SKIP (source workspace not found)")
            failed += 1
            continue

        experiment_workspace = _prepare_wv_experiment_workspace(source_workspace)

        # Build paths, then override to run WV on the v1 source code
        # (not on _v2_experiment which is created later by optimize_batch_results.py)
        paths = build_paths(
            source_workspace=source_workspace,
            webvoyager_results=wv_results_dir,
        )
        paths.experiment_workspace = experiment_workspace
        paths.webvoyager_v2_results = wv_results_dir

        # Clear existing failed WV results
        if wv_results_dir.exists():
            shutil.rmtree(wv_results_dir)
        wv_results_dir.mkdir(parents=True, exist_ok=True)

        result = phase3_webvoyager_test(
            paths,
            project_id=pid,
            port=3000,
            timeout_seconds=600,
            max_iter=10,
        )

        status = result.get("status", "unknown")
        if status in ("success", "partial"):
            success += 1
            print(f"OK ({status})")
        else:
            failed += 1
            print(f"FAIL ({status}: {result.get('message', '')[:80]})")

    print(f"\n[WV v1] Done: {success} success, {failed} failed\n")


def run_optimize_for_run(run_dir: Path, extra_args: list = None):
    """Run optimize_batch_results.py to redo Phase1 brief + Phase2 OH repair + Phase3 WV v2."""
    print(f"\n{'='*60}")
    print(f"[OPTIMIZE] Starting Phase1 brief + Phase2 + Phase3 WV v2")
    print(f"[OPTIMIZE] Run dir: {run_dir.name}")
    print(f"{'='*60}\n")

    cmd = [
        sys.executable,
        "openhands_integration/optimize_batch_results.py",
        "--run-dir", str(run_dir),
        "--max-iterations", "24",
        "--webvoyager-max-iter", "10",
        "--webvoyager-timeout", "1800",
        "--timeout", "5400",
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    print(f"\n[OPTIMIZE] Finished {run_dir.name}: returncode={result.returncode}")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Re-run WV v1 + Phase2 + WV v2 for LLM inject runs")
    parser.add_argument("--run", action="append", dest="runs", metavar="RUN_NAME",
                        help="Run name(s) to process (default: both 20260418 and 20260419 runs)")
    parser.add_argument("--start", help="Start project id, e.g. 000001")
    parser.add_argument("--end", help="End project id, e.g. 000043")
    parser.add_argument("--skip-wv1", action="store_true",
                        help="Skip WV v1 re-run, go straight to optimize")
    parser.add_argument("--skip-optimize", action="store_true",
                        help="Only re-run WV v1, skip Phase2+WV v2")
    parser.add_argument("--model", default=None, help="Use one explicit model for all LLM calls in this pipeline run")
    parser.add_argument("--source-variant", choices=["default", "ast", "llm"], default="default", help="Source project variant to test in WV v1 reruns")
    parser.add_argument("--results-subdir", default="webvoyager_results", help="Result directory name under run_dir for WV v1 reruns")
    args = parser.parse_args()

    if normalize_model_name(args.model):
        apply_unified_model(args.model)
        print(f"[PIPELINE] Unified model: {os.environ.get('PIPELINE_MODEL')}")

    run_names = args.runs or DEFAULT_RUNS

    for run_name in run_names:
        run_dir = BASE_DIR / "batch_runs" / run_name
        if not run_dir.exists():
            print(f"WARNING: {run_dir} not found, skipping")
            continue

        all_ids = _discover_project_ids(run_dir)

        if args.start:
            all_ids = [pid for pid in all_ids if pid >= args.start]
        if args.end:
            all_ids = [pid for pid in all_ids if pid <= args.end]

        print(f"\n{'#'*60}")
        print(f"# Processing: {run_name}  ({len(all_ids)} projects)")
        print(f"{'#'*60}")

        # Step 1: Re-run WV v1
        if not args.skip_wv1:
            rerun_wv1_for_run(
                run_dir,
                all_ids,
                source_variant=args.source_variant,
                results_subdir=args.results_subdir,
            )
        else:
            print(f"[WV v1] Skipped (--skip-wv1)")

        # Step 2: Phase2 + WV v2 via optimize_batch_results.py
        if not args.skip_optimize:
            extra = []
            if args.start:
                extra += ["--start", args.start]
            if args.end:
                extra += ["--end", args.end]
                if normalize_model_name(args.model):
                    extra += ["--model", normalize_model_name(args.model)]
            run_optimize_for_run(run_dir, extra_args=extra)
        else:
            print(f"[OPTIMIZE] Skipped (--skip-optimize)")

    print("\n=== rerun_full_pipeline.py complete ===")


if __name__ == "__main__":
    main()
