#!/usr/bin/env python3
"""Batch optimizer for one batch_runs/run_xxx directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from dynamic_repair_pipeline import (
    build_paths,
    phase0_freeze_source,
    phase1_build_telemetry_brief,
    phase1_build_telemetry_report,
    phase2_openhands_repair,
    phase3_webvoyager_test,
)


def _count_v1_passes(webvoyager_results: Path) -> int:
    """Count tasks that passed (YES verdict) in the v1 WebVoyager results."""
    import re
    count = 0
    if not webvoyager_results.exists():
        return count
    for task_dir in webvoyager_results.iterdir():
        if not task_dir.is_dir() or not task_dir.name.startswith("task"):
            continue
        log_file = task_dir / "interact_messages.json"
        if not log_file.exists():
            continue
        try:
            msgs = json.loads(log_file.read_text(encoding="utf-8"))
            verdict = "UNKNOWN"
            for m in reversed(msgs):
                if not isinstance(m, dict) or m.get("role") != "assistant":
                    continue
                content = re.sub(r"<think>.*?</think>", "", m.get("content", ""), flags=re.DOTALL)
                if "ANSWER;" not in content:
                    continue
                answer_text = content[content.find("ANSWER;") + 7:].strip()
                first_token = answer_text.split()[0].strip(".,;:").upper() if answer_text.split() else ""
                if first_token == "YES":
                    verdict = "YES"
                elif first_token == "NO":
                    verdict = "NO"
                else:
                    snippet = answer_text[:80].upper()
                    if re.search(r"\bYES\b", snippet):
                        verdict = "YES"
                    elif re.search(r"\bNO\b", snippet):
                        verdict = "NO"
                    else:
                        verdict = "YES"
                break
            if verdict == "YES":
                count += 1
        except Exception:
            pass
    return count


def _rollback_to_v1(source_workspace: Path, experiment_workspace: Path) -> None:
    """Overwrite experiment_workspace backend+frontend with the original v1 source."""
    for subdir in ("frontend", "backend"):
        src = source_workspace / subdir
        dst = experiment_workspace / subdir
        if not src.exists():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        # Copy without node_modules to keep it fast
        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns("node_modules", ".git", "__pycache__"),
            symlinks=True,
        )


def _discover_projects(run_dir: Path) -> List[str]:
    ids: List[str] = []
    for gen_dir in sorted([p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("gen_")]):
        project_id = gen_dir.name.replace("gen_", "")
        source = gen_dir / f"project_{project_id}"
        wv = run_dir / "webvoyager_results" / project_id
        if source.exists() and wv.exists():
            ids.append(project_id)
    return ids


def _load_failed_projects(run_dir: Path) -> List[str]:
    batch_file = run_dir / "batch_results.json"
    if not batch_file.exists():
        return []
    try:
        obj = json.loads(batch_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    failed: List[str] = []
    for item in obj.get("projects", []):
        pid = str(item.get("project_id", "")).zfill(6)
        status = str(item.get("status", "")).lower()
        wv_status = str(item.get("webvoyager_status", "")).lower()
        if status != "completed" or wv_status not in {"success", ""}:
            failed.append(pid)
    return sorted(set(failed))


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch optimize one run directory with dynamic repair SOP")
    parser.add_argument("--run-dir", required=True, help="Path to batch_runs/run_xxx directory")
    parser.add_argument("--max-iterations", type=int, default=24, help="OpenHands repair max iterations (phase2)")
    parser.add_argument("--webvoyager-max-iter", type=int, default=10, help="WebVoyager max_iter for phase3 evaluation")
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--webvoyager-timeout", type=int, default=1800, help="WebVoyager v2 test timeout seconds")
    parser.add_argument("--webvoyager-port", type=int, default=3000, help="WebVoyager v2 test base port")
    parser.add_argument("--debounce-seconds", type=float, default=0.8)
    parser.add_argument("--start", help="Start project id, e.g. 000001")
    parser.add_argument("--end", help="End project id, e.g. 000043")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of projects; 0 means all")
    parser.add_argument("--skip-phase2", action="store_true")
    parser.add_argument("--skip-phase3", action="store_true", help="Skip v2 WebVoyager test after optimization")
    parser.add_argument("--skip-llm-brief", action="store_true", help="Skip LLM telemetry brief extraction step")
    parser.add_argument("--llm-brief-model", default=None, help="Model override for telemetry brief extraction")
    parser.add_argument("--llm-brief-max-chars", type=int, default=180000)
    parser.add_argument("--llm-brief-max-tokens", type=int, default=3500)
    parser.add_argument("--llm-brief-max-rounds", type=int, default=6)
    parser.add_argument("--llm-brief-retries-per-model", type=int, default=3)
    parser.add_argument("--llm-brief-retry-backoff-seconds", type=float, default=2.0)
    parser.add_argument("--failed-only", action="store_true", help="Only optimize projects marked failed/non-success in batch_results.json")
    parser.add_argument("--repair-rounds", type=int, default=1, help="Max OH repair rounds per project; each round uses previous WV logs as fresh input (1=single shot, 2-3=iterative)")
    parser.add_argument(
        "--prompt-template",
        default=str((Path(__file__).parent / "prompts" / "evidence_based_optimization_prompt.txt").resolve()),
    )
    args = parser.parse_args()

    # Ensure standalone batch runs can resolve model credentials.
    workspace_root = Path(__file__).resolve().parent.parent
    load_dotenv(workspace_root / ".env")
    load_dotenv(workspace_root / "alternative_generation" / ".env")

    # Bridge common repo env names to OpenHands-required names when absent.
    if not os.getenv("LLM_API_KEY"):
        os.environ["LLM_API_KEY"] = (
            os.getenv("MINIMAX_API_KEY")
            or os.getenv("WEBVOYAGER_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
    if not os.getenv("LLM_MODEL"):
        base_model = os.getenv("MINIMAX_MODEL") or os.getenv("WEBVOYAGER_MODEL") or os.getenv("DEFAULT_MODEL") or "MiniMax-M2.7-highspeed"
        if base_model and "/" not in base_model:
            base_model = f"openai/{base_model}"
        os.environ["LLM_MODEL"] = base_model
    if not os.getenv("LLM_BASE_URL"):
        os.environ["LLM_BASE_URL"] = (
            os.getenv("MINIMAX_BASE_URL")
            or os.getenv("WEBVOYAGER_BASE_URL")
            or os.getenv("DEEPSEEK_API_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.minimaxi.com/v1"
        )
    os.environ.setdefault("LLM_PROVIDER", "openai")

    run_dir = Path(args.run_dir).resolve()
    prompt_template = Path(args.prompt_template).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"run dir not found: {run_dir}")

    all_ids = _discover_projects(run_dir)
    if args.failed_only:
        failed = set(_load_failed_projects(run_dir))
        all_ids = [pid for pid in all_ids if pid in failed]

    if args.start:
        all_ids = [pid for pid in all_ids if pid >= args.start]
    if args.end:
        all_ids = [pid for pid in all_ids if pid <= args.end]
    if args.limit and args.limit > 0:
        all_ids = all_ids[: args.limit]

    summary: Dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(),
        "total_selected": len(all_ids),
        "projects": [],
    }

    for idx, pid in enumerate(all_ids, start=1):
        source_workspace = run_dir / f"gen_{pid}" / f"project_{pid}"
        webvoyager_results = run_dir / "webvoyager_results" / pid
        item: Dict[str, Any] = {
            "project_id": pid,
            "index": idx,
            "source_workspace": str(source_workspace),
            "webvoyager_results": str(webvoyager_results),
            "status": "unknown",
            "phase0": {},
            "phase1": {},
            "phase1_brief": {},
            "phase2": {},
            "phase3": {},
        }

        try:
            paths = build_paths(source_workspace=source_workspace, webvoyager_results=webvoyager_results)
            item["phase0"] = phase0_freeze_source(paths)
            item["phase1"] = phase1_build_telemetry_report(paths, debounce_seconds=args.debounce_seconds)
            if args.skip_llm_brief:
                item["phase1_brief"] = {"status": "skipped"}
            else:
                item["phase1_brief"] = phase1_build_telemetry_brief(
                    paths=paths,
                    model=args.llm_brief_model,
                    max_chars=args.llm_brief_max_chars,
                    max_tokens=args.llm_brief_max_tokens,
                    max_rounds=args.llm_brief_max_rounds,
                    retries_per_model=args.llm_brief_retries_per_model,
                    retry_backoff_seconds=args.llm_brief_retry_backoff_seconds,
                )
            if args.skip_phase2:
                item["phase2"] = {"status": "skipped"}
            else:
                item["phase2"] = phase2_openhands_repair(
                    paths=paths,
                    prompt_template=prompt_template,
                    max_iterations=args.max_iterations,
                    timeout_seconds=args.timeout,
                    project_id=pid,
                    test_specs_file=Path(__file__).resolve().parent.parent / "data" / "test.jsonl",
                )

            if args.skip_phase3:
                item["phase3"] = {"status": "skipped"}
            else:
                phase2_status = str((item.get("phase2") or {}).get("status", ""))
                if phase2_status in {"success", "skipped"}:
                    item["phase3"] = phase3_webvoyager_test(
                        paths=paths,
                        project_id=pid,
                        port=args.webvoyager_port,
                        timeout_seconds=args.webvoyager_timeout,
                        max_iter=args.webvoyager_max_iter,
                    )
                    # ── Quality gate: rollback if v2 is worse than v1 ──────
                    v1_passes = _count_v1_passes(webvoyager_results)
                    v2_passes = int((item["phase3"] or {}).get("success_count", 0))
                    item["quality_gate"] = {
                        "v1_passes": v1_passes,
                        "v2_passes": v2_passes,
                        "decision": "keep" if v2_passes >= v1_passes else "rollback",
                    }
                    if v2_passes < v1_passes:
                        print(f"  [quality-gate] v2={v2_passes} < v1={v1_passes} — rolling back {pid} to v1")
                        _rollback_to_v1(source_workspace, paths.experiment_workspace)
                    else:
                        print(f"  [quality-gate] v2={v2_passes} >= v1={v1_passes} — keeping v2 for {pid}")
                    # ─────────────────────────────────────────────────────────
                else:
                    item["phase3"] = {"status": "skipped_phase2_failed"}

            # ── Multi-round repair loop ──────────────────────────────────────
            # If repair_rounds > 1 and tasks still fail, use the Phase3 WV logs
            # as fresh telemetry input for another OH repair round.
            # Each round: new Phase1 brief (from prev WV logs) → Phase2 fix → Phase3 eval.
            _cur_paths = paths
            test_specs = Path(__file__).resolve().parent.parent / "data" / "test.jsonl"
            for repair_round in range(2, args.repair_rounds + 1):
                prev_phase3 = item.get(f"phase3_r{repair_round - 1}") or item.get("phase3") or {}
                prev_failed = prev_phase3.get("failed_count", 0)
                prev_status = str(prev_phase3.get("status", ""))
                # Only continue if previous phase3 ran and still has failures
                if prev_status in {"skipped", "skipped_phase2_failed", "no_tasks", "api_key_missing"}:
                    break
                if prev_failed == 0:
                    print(f"  [round {repair_round}] All tasks passed — stopping early.")
                    break
                print(f"  [round {repair_round}] {prev_failed} tasks still failing — re-running with fresh log evidence.")

                # Build new paths: source = experiment workspace, wv_results = prev phase3 output
                prev_wv_results = _cur_paths.webvoyager_v2_results
                new_paths = build_paths(
                    source_workspace=_cur_paths.experiment_workspace,
                    webvoyager_results=prev_wv_results,
                )
                # Keep experiment in the SAME directory — just refresh telemetry and re-repair in-place.
                # This avoids workspace proliferation (_v2_experiment_v2_experiment etc.)
                new_paths.experiment_workspace = _cur_paths.experiment_workspace
                new_paths.webvoyager_v2_results = _cur_paths.experiment_workspace / f"webvoyager_r{repair_round}_results"

                rk = f"_r{repair_round}"
                # Phase1: re-build telemetry brief from new WV logs
                item[f"phase1{rk}"] = phase1_build_telemetry_report(new_paths, debounce_seconds=args.debounce_seconds)
                if not args.skip_llm_brief:
                    item[f"phase1_brief{rk}"] = phase1_build_telemetry_brief(
                        paths=new_paths,
                        model=args.llm_brief_model,
                        max_chars=args.llm_brief_max_chars,
                        max_tokens=args.llm_brief_max_tokens,
                        max_rounds=args.llm_brief_max_rounds,
                        retries_per_model=args.llm_brief_retries_per_model,
                        retry_backoff_seconds=args.llm_brief_retry_backoff_seconds,
                    )
                # Phase2: repair using fresh evidence
                if not args.skip_phase2:
                    item[f"phase2{rk}"] = phase2_openhands_repair(
                        paths=new_paths,
                        prompt_template=prompt_template,
                        max_iterations=args.max_iterations,
                        timeout_seconds=args.timeout,
                        project_id=pid,
                        test_specs_file=test_specs,
                    )
                # Phase3: re-evaluate
                if not args.skip_phase3:
                    p2_status = str((item.get(f"phase2{rk}") or {}).get("status", ""))
                    if p2_status in {"success", "skipped", ""}:
                        item[f"phase3{rk}"] = phase3_webvoyager_test(
                            paths=new_paths,
                            project_id=pid,
                            port=args.webvoyager_port,
                            timeout_seconds=args.webvoyager_timeout,
                            max_iter=args.webvoyager_max_iter,
                        )
                _cur_paths = new_paths
            # ────────────────────────────────────────────────────────────────

            item["status"] = "completed"
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)

        summary["projects"].append(item)

        out = run_dir / "dynamic_repair_batch_summary.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{idx}/{len(all_ids)}] {pid}: {item['status']}")

    summary["finished_at"] = datetime.now().isoformat()
    out = run_dir / "dynamic_repair_batch_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Summary written to: {out}")


if __name__ == "__main__":
    main()
