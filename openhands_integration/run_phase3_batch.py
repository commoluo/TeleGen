#!/usr/bin/env python3
"""Run Phase3 WebVoyager testing on existing v2_experiment projects."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Run Phase3 WebVoyager on existing v2_experiment projects")
    parser.add_argument("--run-dir", required=True, help="Path to batch_runs/run_YYYYMMDD_HHMMSS directory")
    parser.add_argument("--start", type=int, default=1, help="Starting project index (1-based)")
    parser.add_argument("--end", type=int, default=5, help="Ending project index (1-based)")
    parser.add_argument("--port", type=int, default=3000, help="Starting port for WebVoyager testing")
    parser.add_argument("--timeout", type=int, default=1800, help="WebVoyager timeout per project")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"Error: Run directory not found: {run_dir}")
        sys.exit(1)

    results = []

    for i in range(args.start, args.end + 1):
        project_id = f"{i:06d}"
        gen_dir = run_dir / f"gen_{project_id}"
        project_dir = gen_dir / f"project_{project_id}_v2_experiment"

        if not project_dir.exists():
            print(f"Skipping {project_id}: v2_experiment not found at {project_dir}")
            continue

        webvoyager_v2_results = project_dir / "webvoyager_v2_results"
        if webvoyager_v2_results.exists() and any(webvoyager_v2_results.iterdir()):
            print(f"Skipping {project_id}: Phase3 already completed")
            continue

        print(f"\n{'='*60}")
        print(f"Running Phase3 for project {project_id}")
        print(f"{'='*60}")

        # The original source (before v2 experiment)
        source_workspace = gen_dir / f"project_{project_id}"
        # The v2_experiment workspace (already repaired)
        experiment_workspace = project_dir
        webvoyager_results = run_dir / "webvoyager_results" / project_id

        cmd = [
            sys.executable,
            "openhands_integration/dynamic_repair_pipeline.py",
            "--source-workspace",
            str(source_workspace),
            "--webvoyager-results",
            str(webvoyager_results),
            "--experiment-workspace",
            str(experiment_workspace),
            "--phase3-only",
            "--port",
            str(args.port + i - 1),
        ]

        print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, cwd=run_dir.parent.parent)
        print(f"Return code: {result.returncode}")

        phase3_result = {"project_id": project_id, "returncode": result.returncode}

        if (project_dir / "dynamic_repair_summary.json").exists():
            try:
                summary = json.loads((project_dir / "dynamic_repair_summary.json").read_text())
                phase3_result["phase3"] = summary.get("phase3", {})
            except Exception as e:
                print(f"Error reading summary: {e}")

        results.append(phase3_result)

        print(f"\nPhase3 result for {project_id}: {phase3_result.get('phase3', {}).get('status', 'unknown')}")

    summary_file = run_dir / f"phase3_batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nSummary written to: {summary_file}")


if __name__ == "__main__":
    main()
