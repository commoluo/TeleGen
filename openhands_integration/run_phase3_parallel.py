#!/usr/bin/env python3
"""Parallel WebVoyager phase3 runner.

Runs phase3_webvoyager_test across all selected projects using a
ProcessPoolExecutor.  Each worker gets its own exclusive port pair so that
multiple browser+backend instances can run concurrently without collisions.

Port allocation (given --base-port B and --workers W):
    Worker i  →  frontend_port = B + i * 2
                 backend_port  = B + i * 2 + 1

Usage example:
    python3 openhands_integration/run_phase3_parallel.py \\
        --run-dir batch_runs/run_20260324_205358 \\
        --workers 4 \\
        --max-iter 10 \\
        --base-port 5100 \\
        --timeout 1800
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Make sure sibling modules are importable when run from any CWD.
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from dynamic_repair_pipeline import build_paths, phase3_webvoyager_test


# ---------------------------------------------------------------------------
# Worker function (runs in a child process)
# ---------------------------------------------------------------------------

def _run_one(args_tuple: Tuple) -> Dict:
    """Top-level function (picklable) executed in a worker process."""
    pid, run_dir_str, frontend_port, backend_port, max_iter, timeout = args_tuple

    run_dir = Path(run_dir_str)
    source_workspace = run_dir / f"gen_{pid}" / f"project_{pid}"
    webvoyager_results = run_dir / "webvoyager_results" / pid

    paths = build_paths(
        source_workspace=source_workspace,
        webvoyager_results=webvoyager_results,
    )

    # Reload env inside child process (env is copied from parent but dotenv
    # files are not auto-sourced in forked processes on some platforms).
    workspace_root = Path(run_dir_str).parent.parent if "batch_runs" in run_dir_str else Path(run_dir_str).parent
    # Try a few candidate locations for .env
    for dotenv_path in [
        workspace_root / ".env",
        workspace_root / "alternative_generation" / ".env",
    ]:
        if dotenv_path.exists():
            load_dotenv(dotenv_path, override=False)

    try:
        result = phase3_webvoyager_test(
            paths=paths,
            project_id=pid,
            port=frontend_port,
            backend_port=backend_port,
            timeout_seconds=timeout,
            max_iter=max_iter,
        )
    except Exception as exc:
        result = {
            "status": "exception",
            "message": str(exc),
            "webvoyager_output_dir": str(paths.webvoyager_v2_results),
        }

    return {
        "project_id": pid,
        "frontend_port": frontend_port,
        "backend_port": backend_port,
        "phase3": result,
    }


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

def _discover_projects(run_dir: Path) -> List[str]:
    ids: List[str] = []
    for gen_dir in sorted(
        p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("gen_")
    ):
        pid = gen_dir.name.replace("gen_", "")
        source = gen_dir / f"project_{pid}"
        wv = run_dir / "webvoyager_results" / pid
        if source.exists() and wv.exists():
            ids.append(pid)
    return ids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parallel WebVoyager phase3 runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--run-dir", required=True, help="batch_runs/run_xxx directory")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--max-iter", type=int, default=10, help="WebVoyager max_iter per task")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout per project (seconds)")
    parser.add_argument(
        "--base-port",
        type=int,
        default=5100,
        help="Base port; worker i uses frontend=base+i*2, backend=base+i*2+1",
    )
    parser.add_argument("--start", default=None, help="Start project id e.g. 000001")
    parser.add_argument("--end", default=None, help="End project id e.g. 000041")
    parser.add_argument("--limit", type=int, default=0, help="Max projects to run (0=all)")
    args = parser.parse_args()

    # Load credentials in the main process (children inherit env).
    workspace_root = Path(__file__).resolve().parent.parent
    load_dotenv(workspace_root / ".env")
    load_dotenv(workspace_root / "alternative_generation" / ".env")

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"run_dir not found: {run_dir}")

    all_ids = _discover_projects(run_dir)
    if args.start:
        all_ids = [p for p in all_ids if p >= args.start]
    if args.end:
        all_ids = [p for p in all_ids if p <= args.end]
    if args.limit and args.limit > 0:
        all_ids = all_ids[: args.limit]

    total = len(all_ids)
    workers = min(args.workers, total)
    print(f"Projects selected: {total}  |  Workers: {workers}  |  max_iter: {args.max_iter}")
    print(f"Base port: {args.base_port}  (workers use ports {args.base_port}–{args.base_port + workers * 2 - 1})")

    # Build job list: assign port slots round-robin to workers.
    jobs: List[Tuple] = []
    for i, pid in enumerate(all_ids):
        slot = i % workers
        frontend_port = args.base_port + slot * 2
        backend_port = args.base_port + slot * 2 + 1
        jobs.append((pid, str(run_dir), frontend_port, backend_port, args.max_iter, args.timeout))

    summary = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(),
        "workers": workers,
        "max_iter": args.max_iter,
        "total_selected": total,
        "projects": [],
    }
    summary_path = run_dir / "phase3_parallel_summary.json"

    finished = 0
    # Use ProcessPoolExecutor so each browser instance runs in its own process.
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(_run_one, job): job for job in jobs}
        for future in as_completed(future_map):
            try:
                res = future.result()
            except Exception as exc:
                job = future_map[future]
                res = {
                    "project_id": job[0],
                    "frontend_port": job[2],
                    "backend_port": job[3],
                    "phase3": {"status": "exception", "message": str(exc)},
                }
            finished += 1
            p3 = res.get("phase3", {})
            print(
                f"[{finished}/{total}] {res['project_id']}  "
                f"status={p3.get('status')}  "
                f"ports={res['frontend_port']}/{res['backend_port']}"
            )
            summary["projects"].append(res)
            # Persist after every completion so progress survives crashes.
            summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    summary["finished_at"] = datetime.now().isoformat()
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. Summary: {summary_path}")


if __name__ == "__main__":
    main()
