#!/usr/bin/env python3
"""Batch optimizer for one batch_runs/run_xxx directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

from experiment_metadata import update_run_metadata
from model_config import apply_unified_model, normalize_model_name
from webvoyager_eval import count_successes

from dynamic_repair_pipeline import (
    build_paths,
    derive_experiment_workspace,
    phase0_freeze_source,
    phase1_build_telemetry_brief,
    phase1_build_telemetry_report,
    phase2_openhands_repair,
    phase3_webvoyager_test,
)


def _clear_proxy_env() -> None:
    """Remove proxy env vars that break local WebVoyager/httpx runs."""
    for var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(var, None)


def _count_v1_passes(webvoyager_results: Path) -> int:
    """Count tasks that passed using the WebVoyager-style auto evaluator."""
    return count_successes(webvoyager_results)


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


def _resolve_source_workspace(run_dir: Path, project_id: str, source_variant: str) -> Path:
    gen_dir = run_dir / f"gen_{project_id}"
    variant = (source_variant or "default").strip().lower()
    if variant == "clean":
        return gen_dir / f"project_{project_id}"
    if variant == "llm":
        return gen_dir / f"project_{project_id}_LLM"

    generation_report = gen_dir / "generation_report.json"
    if generation_report.exists():
        try:
            payload = json.loads(generation_report.read_text(encoding="utf-8"))
            output_path = Path(str(payload.get("output") or "")).name
            if output_path == f"project_{project_id}_LLM":
                return gen_dir / output_path
        except Exception:
            pass

    return gen_dir / f"project_{project_id}"


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


def _load_existing_summary(summary_file: Path) -> Dict[str, object]:
    if not summary_file.exists():
        return {}
    try:
        payload = json.loads(summary_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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
    parser.add_argument("--source-variant", choices=["default", "clean", "ast", "llm"], default="default", help="Select source workspace variant for phase2/phase3")
    parser.add_argument("--summary-file", default=None, help="Write summary to this file instead of dynamic_repair_batch_summary.json")
    parser.add_argument("--branch-name", default=None, help="Label this optimize run, e.g. logged or no_log")
    parser.add_argument("--skip-telemetry-report", action="store_true", help="Skip sanitized telemetry report generation before repair")
    parser.add_argument("--skip-phase2", action="store_true")
    parser.add_argument("--skip-phase3", action="store_true", help="Skip v2 WebVoyager test after optimization")
    parser.add_argument("--skip-llm-brief", action="store_true", help="Skip LLM telemetry brief extraction step")
    parser.add_argument("--llm-brief-model", default=None, help="Model override for telemetry brief extraction")
    parser.add_argument("--model", default=None, help="Use one explicit model for all LLM calls in this optimize run")
    parser.add_argument("--llm-brief-max-chars", type=int, default=40000)
    parser.add_argument("--llm-brief-max-tokens", type=int, default=1500)
    parser.add_argument("--llm-brief-max-rounds", type=int, default=2)
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
    _clear_proxy_env()

    unified_model = normalize_model_name(args.model)
    if unified_model:
        apply_unified_model(unified_model)
        args.llm_brief_model = unified_model

    # Bridge common repo env names to OpenHands-required names when absent.
    if os.getenv("DEEPSEEK_API_KEY"):
        os.environ["LLM_API_KEY"] = os.getenv("DEEPSEEK_API_KEY", "")
        os.environ["LLM_MODEL"] = os.getenv("DEEPSEEK_MODEL") or "deepseek/deepseek-v4-flash"
        if "/" not in os.environ["LLM_MODEL"]:
            os.environ["LLM_MODEL"] = f"deepseek/{os.environ['LLM_MODEL']}"
        os.environ["LLM_BASE_URL"] = os.getenv("DEEPSEEK_API_BASE_URL") or "https://api.deepseek.com"
        os.environ["LLM_PROVIDER"] = "deepseek"
    elif not os.getenv("LLM_API_KEY"):
        os.environ["LLM_API_KEY"] = (
            os.getenv("QWEN_API_KEY")
            or os.getenv("WEBVOYAGER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
    if not os.getenv("LLM_MODEL"):
        base_model = os.getenv("DEEPSEEK_MODEL") or os.getenv("PIPELINE_MODEL") or os.getenv("DEFAULT_MODEL") or "deepseek-v4-flash"
        if base_model and "/" not in base_model:
            base_model = f"deepseek/{base_model}"
        os.environ["LLM_MODEL"] = base_model
    if not os.getenv("LLM_BASE_URL"):
        os.environ["LLM_BASE_URL"] = (
            os.getenv("QWEN_API_BASE_URL")
            or os.getenv("WEBVOYAGER_BASE_URL")
            or os.getenv("DEEPSEEK_API_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    os.environ.setdefault("LLM_PROVIDER", "openai")

    if unified_model:
        print(f"[OPTIMIZE] Unified model: {unified_model}")

    run_dir = Path(args.run_dir).resolve()
    prompt_template = Path(args.prompt_template).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"run dir not found: {run_dir}")

    metadata_file = update_run_metadata(
        run_dir,
        {
            "optimize_entrypoint": "openhands_integration/optimize_batch_results.py",
            "stages": {
                "optimize": {
                    "started_at": datetime.now().isoformat(),
                    "steps": [
                        "telemetry_report" if not args.skip_telemetry_report else "skip_telemetry_report",
                        "telemetry_brief" if not args.skip_llm_brief else "skip_telemetry_brief",
                        "v2_repair",
                        "wv_v2",
                    ],
                    "branch_name": args.branch_name,
                    "source_variant": args.source_variant,
                    "repair": {
                        "enabled": not args.skip_phase2,
                        "max_iterations": args.max_iterations,
                        "timeout_seconds": args.timeout,
                        "rounds": args.repair_rounds,
                        "prompt_template": str(prompt_template),
                    },
                    "telemetry_brief": {
                        "enabled": not args.skip_llm_brief,
                        "model": args.llm_brief_model or os.getenv("DEEPSEEK_MODEL") or os.getenv("PIPELINE_MODEL") or None,
                        "max_chars": args.llm_brief_max_chars,
                        "max_tokens": args.llm_brief_max_tokens,
                        "max_rounds": args.llm_brief_max_rounds,
                        "retries_per_model": args.llm_brief_retries_per_model,
                    },
                    "webvoyager_v2": {
                        "enabled": not args.skip_phase3,
                        "max_iter": args.webvoyager_max_iter,
                        "timeout_seconds": args.webvoyager_timeout,
                        "port": args.webvoyager_port,
                        "eval_model": os.getenv("WEBVOYAGER_EVAL_MODEL") or None,
                    },
                },
            },
        },
    )
    print(f"[OPTIMIZE] Metadata file: {metadata_file}")

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

    summary_file = Path(args.summary_file).expanduser().resolve() if args.summary_file else run_dir / "dynamic_repair_batch_summary.json"
    existing_summary = _load_existing_summary(summary_file)
    project_order: List[str] = []
    project_items_by_id: Dict[str, Dict[str, object]] = {}
    for existing_item in existing_summary.get("projects", []):
        if not isinstance(existing_item, dict):
            continue
        project_id = str(existing_item.get("project_id", "")).zfill(6)
        if not project_id:
            continue
        project_order.append(project_id)
        project_items_by_id[project_id] = existing_item

    summary: Dict[str, object] = {
        "run_dir": str(run_dir),
        "started_at": existing_summary.get("started_at") or datetime.now().isoformat(),
        "branch_name": args.branch_name,
        "source_variant": args.source_variant,
        "total_selected": max(int(existing_summary.get("total_selected", 0) or 0), len(all_ids), len(project_order)),
        "projects": [project_items_by_id[project_id] for project_id in project_order],
    }

    for idx, pid in enumerate(all_ids, start=1):
        source_workspace = _resolve_source_workspace(run_dir, pid, args.source_variant)
        webvoyager_results = run_dir / "webvoyager_results" / pid
        item: Dict[str, object] = {
            "project_id": pid,
            "index": idx,
            "source_workspace": str(source_workspace),
            "experiment_workspace": str(derive_experiment_workspace(source_workspace)),
            "webvoyager_results": str(webvoyager_results),
            "status": "unknown",
            "phase0": {},
            "phase1": {},
            "phase1_brief": {},
            "phase2": {},
            "phase3": {},
        }

        try:
            print(f"\n{'─'*60}", flush=True)
            print(f"[{idx}/{len(all_ids)}] {pid} — start", flush=True)
            print(f"{'─'*60}", flush=True)
            paths = build_paths(source_workspace=source_workspace, webvoyager_results=webvoyager_results, branch_name=args.branch_name)
            if args.branch_name:
                print(f"[{idx}/{len(all_ids)}] [{pid}] Branch: {args.branch_name} source_variant={args.source_variant}", flush=True)
            print(f"[{idx}/{len(all_ids)}] [{pid}] Phase0: freezing source ...", flush=True)
            item["phase0"] = phase0_freeze_source(paths)
            if args.skip_telemetry_report:
                item["phase1"] = {"status": "skipped"}
            else:
                print(f"[{idx}/{len(all_ids)}] [{pid}] Phase1: building telemetry report ...", flush=True)
                item["phase1"] = phase1_build_telemetry_report(paths, debounce_seconds=args.debounce_seconds)
            if args.skip_llm_brief:
                item["phase1_brief"] = {"status": "skipped"}
            else:
                print(f"[{idx}/{len(all_ids)}] [{pid}] Phase1 brief: LLM extraction (model={args.llm_brief_model or 'default'}) ...", flush=True)
                item["phase1_brief"] = phase1_build_telemetry_brief(
                    paths=paths,
                    model=args.llm_brief_model,
                    max_chars=args.llm_brief_max_chars,
                    max_tokens=args.llm_brief_max_tokens,
                    max_rounds=args.llm_brief_max_rounds,
                    retries_per_model=args.llm_brief_retries_per_model,
                    retry_backoff_seconds=args.llm_brief_retry_backoff_seconds,
                )
                print(f"[{idx}/{len(all_ids)}] [{pid}] Phase1 brief: {item['phase1_brief'].get('status', '?')}", flush=True)
                if str(item["phase1_brief"].get("status", "")).lower() != "success":
                    item["phase2"] = {"status": "skipped_phase1_brief_failed"}
                    item["phase3"] = {"status": "skipped_phase1_brief_failed"}
                    raise RuntimeError("Phase1 telemetry brief failed; log compression is required before repair")
            if args.skip_phase2:
                item["phase2"] = {"status": "skipped"}
            else:
                print(f"[{idx}/{len(all_ids)}] [{pid}] Phase2: OpenHands repair (max_iter={args.max_iterations}, timeout={args.timeout}s) ...", flush=True)
                item["phase2"] = phase2_openhands_repair(
                    paths=paths,
                    prompt_template=prompt_template,
                    max_iterations=args.max_iterations,
                    timeout_seconds=args.timeout,
                    project_id=pid,
                    test_specs_file=Path(__file__).resolve().parent.parent / "data" / "test.jsonl",
                )
                print(f"[{idx}/{len(all_ids)}] [{pid}] Phase2: {item['phase2'].get('status', '?')}", flush=True)

            if args.skip_phase3:
                item["phase3"] = {"status": "skipped"}
            else:
                phase2_status = str((item.get("phase2") or {}).get("status", ""))
                if phase2_status in {"success", "skipped"}:
                    print(f"[{idx}/{len(all_ids)}] [{pid}] Phase3: WebVoyager v2 test (timeout={args.webvoyager_timeout}s) ...", flush=True)
                    item["phase3"] = phase3_webvoyager_test(
                        paths=paths,
                        project_id=pid,
                        port=args.webvoyager_port,
                        timeout_seconds=args.webvoyager_timeout,
                        max_iter=args.webvoyager_max_iter,
                    )
                    print(f"[{idx}/{len(all_ids)}] [{pid}] Phase3: {item['phase3'].get('status', '?')} (ok={item['phase3'].get('success_count',0)}, fail={item['phase3'].get('failed_count',0)})", flush=True)
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
                    branch_name=args.branch_name,
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
                    if str((item.get(f"phase1_brief{rk}") or {}).get("status", "")).lower() != "success":
                        item["status"] = "failed"
                        item["error"] = f"Phase1 telemetry brief failed in repair round {repair_round}"
                        raise RuntimeError(item["error"])
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

        if pid not in project_items_by_id:
            project_order.append(pid)
        project_items_by_id[pid] = item
        summary["projects"] = [project_items_by_id[project_id] for project_id in project_order]
        summary["total_selected"] = max(int(summary.get("total_selected", 0) or 0), len(project_order), len(all_ids))

        out = summary_file
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{idx}/{len(all_ids)}] {pid}: {item['status']}")

    summary["finished_at"] = datetime.now().isoformat()
    out = summary_file
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Summary written to: {out}")


if __name__ == "__main__":
    main()
