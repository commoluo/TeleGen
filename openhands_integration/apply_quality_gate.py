#!/usr/bin/env python3
"""
Apply quality gate (rollback) retroactively to 001-030 projects in a run directory.

For each project:
  - Count v1 passes from webvoyager_results/{pid}/
  - Count v2 passes from gen_{pid}/project_{pid}_v2_experiment/webvoyager_v2_results/
  - If v2 < v1: rollback (copy v1 frontend/backend back to v2_experiment dir)
  - Update dynamic_repair_batch_summary.json with quality_gate field

Usage:
    python openhands_integration/apply_quality_gate.py --run-dir batch_runs/run_20260401_213830 --start 000001 --end 000030
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional


def _extract_verdict(msgs: list) -> str:
    """Extract YES/NO/UNKNOWN verdict from interact_messages list.
    Exactly matches _count_v1_passes logic in optimize_batch_results.py.
    """
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        content = re.sub(r"<think>.*?</think>", "", m.get("content", ""), flags=re.DOTALL)
        if "ANSWER;" not in content:
            continue
        answer_text = content[content.find("ANSWER;") + 7:].strip()
        first = answer_text.split()[0].strip(".,;:").upper() if answer_text.split() else ""
        if first == "YES":
            return "YES"
        if first == "NO":
            return "NO"
        snippet = answer_text[:120].upper()
        if re.search(r"\bYES\b", snippet):
            return "YES"
        if re.search(r"\bNO\b", snippet):
            return "NO"
        return "YES"  # ANSWER; found but ambiguous → default YES
    return "UNKNOWN"


def count_passes(wv_dir: Path) -> int:
    """Count passing tasks in a webvoyager results directory."""
    if not wv_dir.exists():
        return 0
    passes = 0
    for task_dir in sorted(wv_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        msg_file = task_dir / "interact_messages.json"
        if not msg_file.exists():
            continue
        try:
            msgs = json.loads(msg_file.read_text(encoding="utf-8"))
            if _extract_verdict(msgs) == "YES":
                passes += 1
        except Exception as e:
            print(f"  Warning: could not parse {msg_file}: {e}")
    return passes


def rollback_to_v1(source_workspace: Path, experiment_workspace: Path) -> None:
    """Overwrite experiment_workspace backend+frontend with v1 source."""
    for subdir in ("frontend", "backend"):
        src = source_workspace / subdir
        dst = experiment_workspace / subdir
        if not src.exists():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns("node_modules", ".git", "__pycache__"),
            symlinks=True,
        )


def load_summary(run_dir: Path) -> list:
    summary_path = run_dir / "dynamic_repair_batch_summary.json"
    if not summary_path.exists():
        return []
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        return data.get("projects", [])
    except Exception:
        return []


def save_summary(run_dir: Path, projects: list) -> None:
    summary_path = run_dir / "dynamic_repair_batch_summary.json"
    existing = {}
    if summary_path.exists():
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing["projects"] = projects
    existing["last_updated"] = datetime.now().isoformat()
    summary_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved summary → {summary_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply quality gate retroactively to batch run projects")
    parser.add_argument("--run-dir", required=True, help="Path to batch_runs/run_xxx directory")
    parser.add_argument("--start", default="000001", help="Start project id (inclusive)")
    parser.add_argument("--end", default="000030", help="End project id (inclusive)")
    parser.add_argument("--dry-run", action="store_true", help="Print decisions without actually rolling back")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")

    # Load existing summary to avoid overwriting gate data that already exists
    all_projects = load_summary(run_dir)
    proj_map: dict[str, dict] = {p["project_id"]: p for p in all_projects}

    stats = {
        "total": 0, "skipped_no_v2": 0, "keep": 0, "rollback": 0,
        "already_gated": 0,
        "v1_total": 0, "v2_total_before_gate": 0, "v2_total_after_gate": 0,
    }

    pids = []
    for i in range(int(args.start), int(args.end) + 1):
        pids.append(f"{i:06d}")

    print(f"\n{'='*60}")
    print(f"Quality Gate Application: {args.start} → {args.end}")
    print(f"Run dir: {run_dir}")
    print(f"Dry run: {args.dry_run}")
    print(f"{'='*60}\n")

    rows = []
    for pid in pids:
        stats["total"] += 1

        # Skip if already has gate decision
        existing_gate = (proj_map.get(pid) or {}).get("quality_gate")
        if existing_gate and not args.dry_run:
            stats["already_gated"] += 1
            v1p = existing_gate.get("v1_passes", 0)
            v2p = existing_gate.get("v2_passes", 0)
            decision = existing_gate.get("decision", "?")
            stats["v1_total"] += v1p
            stats["v2_total_before_gate"] += v2p
            stats["v2_total_after_gate"] += v1p if decision == "rollback" else v2p
            rows.append((pid, v1p, v2p, decision, "skipped (already gated)"))
            continue

        v1_dir = run_dir / "webvoyager_results" / pid
        v2_dir = run_dir / f"gen_{pid}" / f"project_{pid}_v2_experiment" / "webvoyager_v2_results"
        source_workspace = run_dir / f"gen_{pid}" / f"project_{pid}"
        experiment_workspace = run_dir / f"gen_{pid}" / f"project_{pid}_v2_experiment"

        if not v2_dir.exists():
            stats["skipped_no_v2"] += 1
            rows.append((pid, "?", "?", "SKIP", "no v2 WV results"))
            print(f"  {pid}: SKIP — no v2 WV results at {v2_dir}")
            continue

        v1_passes = count_passes(v1_dir)
        v2_passes = count_passes(v2_dir)
        stats["v1_total"] += v1_passes
        stats["v2_total_before_gate"] += v2_passes

        if v2_passes >= v1_passes:
            decision = "keep"
            stats["keep"] += 1
            stats["v2_total_after_gate"] += v2_passes
            label = "keep v2"
        else:
            decision = "rollback"
            stats["rollback"] += 1
            stats["v2_total_after_gate"] += v1_passes
            label = f"ROLLBACK to v1 (v2={v2_passes} < v1={v1_passes})"

        rows.append((pid, v1_passes, v2_passes, decision, label))
        delta = v2_passes - v1_passes
        print(f"  {pid}: v1={v1_passes}, v2={v2_passes} ({delta:+d}) → {label}")

        # Update quality gate in project record
        gate_data = {
            "v1_passes": v1_passes,
            "v2_passes": v2_passes,
            "decision": decision,
            "applied_by": "apply_quality_gate.py",
            "applied_at": datetime.now().isoformat(),
        }

        if not args.dry_run:
            if decision == "rollback":
                if source_workspace.exists() and experiment_workspace.exists():
                    rollback_to_v1(source_workspace, experiment_workspace)
                    print(f"    ↩ Rolled back {pid} frontend/backend to v1")
                else:
                    print(f"    Warning: could not rollback {pid} — source or experiment dir missing")

            # Upsert project record in summary
            if pid in proj_map:
                proj_map[pid]["quality_gate"] = gate_data
            else:
                # Create minimal record
                proj_map[pid] = {
                    "project_id": pid,
                    "quality_gate": gate_data,
                }

    # Print summary table
    print(f"\n{'='*60}")
    print(f"{'PID':<12} {'v1':>4} {'v2':>4} {'Decision':<12} Note")
    print(f"{'-'*60}")
    for pid, v1, v2, decision, note in rows:
        print(f"  {pid}  {str(v1):>4} {str(v2):>4}  {decision:<12}  {note}")

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Total projects checked:    {stats['total']}")
    print(f"  Already gated (skipped):   {stats['already_gated']}")
    print(f"  Skipped (no v2 WV):        {stats['skipped_no_v2']}")
    print(f"  Keep v2:                   {stats['keep']}")
    print(f"  Rollback to v1:            {stats['rollback']}")
    print(f"  v1 total passes:           {stats['v1_total']}")
    print(f"  v2 total passes (before):  {stats['v2_total_before_gate']}")
    print(f"  v2 total passes (after):   {stats['v2_total_after_gate']}")
    delta = stats["v2_total_after_gate"] - stats["v1_total"]
    print(f"  Net improvement:           {delta:+d}")

    if not args.dry_run:
        # Rebuild complete sorted project list and save
        merged_list = sorted(proj_map.values(), key=lambda p: p.get("project_id", ""))
        save_summary(run_dir, merged_list)

    print(f"\nDone{'  (DRY RUN — no changes written)' if args.dry_run else ''}.")


if __name__ == "__main__":
    main()
