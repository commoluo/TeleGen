#!/usr/bin/env python3
"""Build a minimal, fast, reproducible human-validation package for
manually checking WebVoyager judgments on the final TeleGen outputs.

Usage:
    python scripts/build_human_validation_package.py \
        --experiment-root . \
        --output human_validation_telegen \
        --seed 20260713 \
        --num-success 30 \
        --num-failure 30 \
        --blind
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ────────────────────────────────────────────────────────

DEFAULT_SEED = 20260713
EXPECTED_SUCCESS = 493
EXPECTED_TOTAL = 647
EXPECTED_RATE = 76.2

# The canonical CSV that lists every project and its summary path.
BASELINE_CSV = (
    "batch_runs/official/flash_llm_injection_analysis/"
    "baseline_results_000001_000101.json"
)
BASELINE_CSV_CSV = (
    "batch_runs/official/flash_llm_injection_analysis/"
    "baseline_results_000001_000101.csv"
)
SUMMARY_JSON = (
    "batch_runs/official/flash_llm_injection_analysis/"
    "summary_000001_000101.json"
)
TASKS_JSONL = "data/test.jsonl"

# Workspace root for path boundary validation (set in main())
_WORKSPACE_ROOT: Path = Path(".")

# ── Data loading ─────────────────────────────────────────────────────

def load_tasks(workspace: Path) -> Dict[str, dict]:
    """Load project / task definitions from data/test.jsonl.

    Returns a dict keyed by project_id (e.g. "000001") whose value is the
    full JSON object including the ``ui_instruct`` list.
    """
    tasks_path = workspace / TASKS_JSONL
    if not tasks_path.exists():
        sys.exit(f"ERROR: Task definitions not found: {tasks_path}")
    result: Dict[str, dict] = {}
    with open(tasks_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            pid = str(obj.get("id", "")).zfill(6)
            result[pid] = obj
    return result


def load_project_summaries(workspace: Path) -> List[dict]:
    """Load the per-project summary paths from the baseline CSV."""
    csv_path = workspace / BASELINE_CSV_CSV
    if not csv_path.exists():
        sys.exit(f"ERROR: Baseline CSV not found: {csv_path}")
    rows: List[dict] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def verify_493_647(workspace: Path) -> dict:
    """Verify that the identified TeleGen result is 493/647."""
    summary_path = workspace / SUMMARY_JSON
    if not summary_path.exists():
        sys.exit(f"ERROR: Summary JSON not found: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    logged_total = summary.get("logged_total", 0)
    total_tasks = summary.get("total_tasks", 0)
    if logged_total != EXPECTED_SUCCESS or total_tasks != EXPECTED_TOTAL:
        sys.exit(
            f"ERROR: Expected {EXPECTED_SUCCESS}/{EXPECTED_TOTAL} but found "
            f"{logged_total}/{total_tasks} in {summary_path}"
        )
    return summary


# ── Candidate manifest ──────────────────────────────────────────────

def build_candidate_manifest(
    workspace: Path,
    project_rows: List[dict],
    tasks_data: Dict[str, dict],
) -> List[dict]:
    """Build the complete candidate manifest from final TeleGen WV2 results.

    Each candidate is a dict with all required fields.
    """
    candidates: List[dict] = []
    errors: List[str] = []

    for prow in project_rows:
        pid = str(prow["project_id"]).zfill(6)
        summary_path_str = prow["summary_path"]
        summary_full = workspace / summary_path_str
        if not summary_full.exists():
            errors.append(f"Missing summary: {summary_full}")
            continue

        summary = json.loads(summary_full.read_text(encoding="utf-8"))
        proj_dir = summary_full.parent
        wv2_dir = proj_dir / f"gen_{pid}" / f"project_{pid}_v2_LLM" / "webvoyager_v2_results"

        if not wv2_dir.is_dir():
            errors.append(f"Missing WV2 dir for {pid}: {wv2_dir}")
            continue

        task_defs = tasks_data.get(pid, {}).get("ui_instruct", [])
        app_source = proj_dir / f"gen_{pid}" / f"project_{pid}_v2_LLM"

        for task_dir_name in sorted(os.listdir(wv2_dir)):
            task_dir = wv2_dir / task_dir_name
            if not task_dir.is_dir():
                continue

            # Parse task index from "task000015--1"
            if "--" not in task_dir_name:
                continue
            task_idx_str = task_dir_name.rsplit("--", 1)[1]
            try:
                task_idx = int(task_idx_str)
            except ValueError:
                continue

            eval_path = task_dir / "webvoyager_auto_eval.json"
            if not eval_path.exists():
                errors.append(f"Missing eval: {eval_path}")
                continue

            eval_data = json.loads(eval_path.read_text(encoding="utf-8"))
            status_raw = eval_data.get("status", "").strip()
            is_success = status_raw.upper() == "SUCCESS"

            # Get task definition (1-indexed in dir, 0-indexed in list)
            task_def = {}
            if 1 <= task_idx <= len(task_defs):
                task_def = task_defs[task_idx - 1]
            else:
                errors.append(
                    f"Task index {task_idx} out of range for {pid} "
                    f"(has {len(task_defs)} tasks)"
                )

            task_desc = task_def.get("task", "")
            expected_result = task_def.get("expected_result", "")
            task_cat = task_def.get("task_category", {})
            primary_cat = task_cat.get("primary_category", "Unknown")
            subcats = task_cat.get("subcategories", [])

            # Trajectory path
            traj_path = task_dir / "interact_messages.json"

            # Screenshot paths
            screenshots = sorted(
                [f for f in os.listdir(task_dir) if f.startswith("screenshot") and f.endswith(".png")]
            )
            screenshot_paths = [str(task_dir / s) for s in screenshots]
            final_screenshot = screenshot_paths[-1] if screenshot_paths else ""

            # WebVoyager answer/observation
            wv_answer = eval_data.get("answer", "")
            wv_evaluator_response = eval_data.get("evaluator_response", "")
            wv_observation = wv_answer or wv_evaluator_response

            # Check for infrastructure-only failures (no screenshots AND no trajectory)
            has_screenshots = bool(screenshots)
            has_trajectory = traj_path.exists()
            is_infra_only = not has_screenshots and not has_trajectory

            if is_infra_only:
                errors.append(
                    f"Excluded (infrastructure-only, no evidence): {pid}/{task_dir_name}"
                )
                continue

            candidate = {
                "project_id": pid,
                "task_id": task_dir_name,
                "task_idx": task_idx,
                "task_description": task_desc,
                "expected_result": expected_result,
                "task_category": primary_cat,
                "task_subcategories": "; ".join(subcats) if subcats else "",
                "wv_verdict": "Success" if is_success else "Failure",
                "wv_status_raw": status_raw,
                "wv_answer": wv_answer,
                "wv_evaluator_response": wv_evaluator_response,
                "wv_observation": wv_observation,
                "trajectory_path": str(traj_path),
                "screenshot_paths": screenshot_paths,
                "final_screenshot_path": final_screenshot,
                "app_source_path": str(app_source),
                "eval_source_path": str(eval_path),
                "task_dir": str(task_dir),
            }
            candidates.append(candidate)

    return candidates, errors


# ── Sampling ─────────────────────────────────────────────────────────

def stratified_sample(
    candidates: List[dict],
    num_success: int,
    num_failure: int,
    seed: int,
) -> Tuple[List[dict], List[dict], dict]:
    """Deterministic stratified random sampling.

    Within each stratum (success / failure):
    1. Prefer at most one task per project.
    2. If insufficient, allow at most two tasks per project.
    3. Preserve proportional category coverage.
    """
    rng = random.Random(seed)

    success_pool = [c for c in candidates if c["wv_verdict"] == "Success"]
    failure_pool = [c for c in candidates if c["wv_verdict"] == "Failure"]

    if len(success_pool) < num_success:
        sys.exit(
            f"ERROR: Only {len(success_pool)} success candidates, need {num_success}"
        )
    if len(failure_pool) < num_failure:
        sys.exit(
            f"ERROR: Only {len(failure_pool)} failure candidates, need {num_failure}"
        )

    def sample_stratum(
        pool: List[dict], n: int, label: str, excluded_projects: Optional[set] = None
    ) -> Tuple[List[dict], dict]:
        # Category distribution in the pool
        cat_counts = Counter(c["task_category"] for c in pool)
        # Target per category (proportional, at least 1 if category exists)
        total = len(pool)
        targets: Dict[str, int] = {}
        remaining = n
        for cat, cnt in sorted(cat_counts.items()):
            proportional = round(n * cnt / total)
            targets[cat] = min(proportional, cnt)
            remaining -= targets[cat]
        # Distribute remainder round-robin to largest categories
        if remaining > 0:
            for cat in sorted(cat_counts, key=lambda x: -cat_counts[x]):
                if remaining <= 0:
                    break
                room = cat_counts[cat] - targets[cat]
                add = min(remaining, room)
                targets[cat] += add
                remaining -= add
        if remaining > 0:
            # Fallback: relax to raw counts
            for cat in sorted(cat_counts, key=lambda x: -cat_counts[x]):
                if remaining <= 0:
                    break
                room = cat_counts[cat] - targets[cat]
                add = min(remaining, room)
                targets[cat] += add
                remaining -= add

        # For each category, sample with project constraint
        selected: List[dict] = []
        used_projects: Counter = Counter()
        max_per_project = 1

        def try_sample(max_pp: int, exclude_projects: Optional[set] = None) -> List[dict]:
            sel: List[dict] = []
            used: Counter = Counter()
            for cat, target in sorted(targets.items()):
                cat_pool = [c for c in pool if c["task_category"] == cat]
                rng.shuffle(cat_pool)
                cat_selected: List[dict] = []
                # First pass: respect excluded_projects
                for c in cat_pool:
                    if len(cat_selected) >= target:
                        break
                    pid = c["project_id"]
                    if exclude_projects and pid in exclude_projects:
                        continue
                    if used[pid] < max_pp:
                        cat_selected.append(c)
                        used[pid] += 1
                # Second pass: fill remaining ignoring exclude_projects
                for c in cat_pool:
                    if len(cat_selected) >= target:
                        break
                    if c not in cat_selected and used[c["project_id"]] < max_pp:
                        cat_selected.append(c)
                        used[c["project_id"]] += 1
                # Third pass: fill remaining ignoring all constraints
                for c in cat_pool:
                    if len(cat_selected) >= target:
                        break
                    if c not in cat_selected:
                        cat_selected.append(c)
                        used[c["project_id"]] += 1
                sel.extend(cat_selected)
            return sel

        selected = try_sample(1, exclude_projects=excluded_projects)
        if len(selected) < n:
            # Relax to 2 per project but still try to avoid excluded projects
            max_per_project = 2
            selected = try_sample(2, exclude_projects=excluded_projects)
        if len(selected) < n:
            # Final relaxation: ignore excluded_projects
            selected = try_sample(2)

        # If still short, fill from remaining pool
        if len(selected) < n:
            sel_ids = {id(c) for c in selected}
            remaining_pool = [c for c in pool if id(c) not in sel_ids]
            rng.shuffle(remaining_pool)
            for c in remaining_pool:
                if len(selected) >= n:
                    break
                selected.append(c)

        # Trim to exactly n
        selected = selected[:n]

        info = {
            "stratum": label,
            "pool_size": len(pool),
            "requested": n,
            "selected": len(selected),
            "max_per_project": max_per_project,
            "category_targets": dict(targets),
            "selected_category_dist": dict(Counter(c["task_category"] for c in selected)),
            "selected_project_dist": dict(Counter(c["project_id"] for c in selected)),
            "projects_with_2_tasks": [
                p for p, cnt in Counter(c["project_id"] for c in selected).items()
                if cnt >= 2
            ],
        }
        return selected, info

    success_selected, success_info = sample_stratum(success_pool, num_success, "success", excluded_projects=None)
    # For failure sampling, prefer projects not already used in success sample
    success_projects = {c["project_id"] for c in success_selected}
    failure_selected, failure_info = sample_stratum(failure_pool, num_failure, "failure", excluded_projects=success_projects)

    sampling_info = {
        "seed": seed,
        "success": success_info,
        "failure": failure_info,
    }
    return success_selected, failure_selected, sampling_info


# ── Path utilities ──────────────────────────────────────────────────

def rel_if_possible(path: str, base: Path) -> str:
    """Return a path relative to *base* if possible, else absolute."""
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def safe_symlink(src: Path, dst: Path, copy: bool = False) -> None:
    """Create a symlink or copy. Never overwrite an existing original.

    Validates that *src* resides within the workspace root to prevent
    symlink attacks or accidental exposure of files outside the repo.
    """
    resolved_src = src.resolve()
    if not resolved_src.exists():
        return
    # Boundary check: src must be inside the workspace root
    try:
        resolved_src.relative_to(_WORKSPACE_ROOT)
    except ValueError:
        sys.exit(
            f"ERROR: Path points outside permitted repository roots: {resolved_src}"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        if src.is_file():
            shutil.copy2(src, dst)
        else:
            shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(src.resolve(), dst)


# ── Trajectory parsing ──────────────────────────────────────────────

def parse_trajectory(traj_path: str) -> List[dict]:
    """Parse interact_messages.json into a list of step dicts."""
    if not traj_path or not os.path.exists(traj_path):
        return []
    with open(traj_path, encoding="utf-8") as f:
        messages = json.load(f)

    steps: List[dict] = []
    current_screenshot = ""
    step_num = 0

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            # Extract screenshot reference and observation text
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text = item.get("text", "")
                            if "screenshot" in text.lower():
                                # Try to extract screenshot number
                                pass
                        elif item.get("type") == "image_url":
                            url = item.get("image_url", {})
                            if isinstance(url, dict):
                                url_str = url.get("url", "")
                                if "screenshot" in url_str:
                                    current_screenshot = url_str.split("/")[-1]
                            elif isinstance(url, str):
                                current_screenshot = url.split("/")[-1]
            elif isinstance(content, str):
                pass  # text observation

        elif role == "assistant":
            step_num += 1
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )

            # Parse thought and action
            thought = ""
            action = ""
            if "Thought:" in text:
                parts = text.split("Action:", 1)
                thought_part = parts[0]
                thought = thought_part.replace("Thought:", "").strip()
                if len(parts) > 1:
                    action = parts[1].strip()
            else:
                thought = text.strip()

            steps.append({
                "step": step_num,
                "thought": thought,
                "action": action,
                "screenshot": current_screenshot,
            })
            current_screenshot = ""

    return steps


# ── HTML generation ────────────────────────────────────────────────

INDEX_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TeleGen Human Validation</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 2rem; background: #f5f5f5; color: #333; }}
  h1 {{ color: #222; }}
  .summary {{ background: #fff; border-radius: 8px; padding: 1rem 1.5rem; margin-bottom: 1.5rem;
              box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
           gap: .75rem; }}
  .card {{ background: #fff; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,.1);
           text-decoration: none; color: #333; transition: transform .1s; }}
  .card:hover {{ transform: translateY(-2px); box-shadow: 0 3px 6px rgba(0,0,0,.15); }}
  .card .id {{ font-weight: 600; font-size: 1.1rem; }}
  .card .status {{ font-size: .85rem; color: #888; margin-top: .3rem; }}
  .done {{ border-left: 4px solid #4caf50; }}
  .pending {{ border-left: 4px solid #e0e0e0; }}
  .stats {{ display: flex; gap: 2rem; margin-bottom: 1rem; }}
  .stat {{ text-align: center; }}
  .stat .num {{ font-size: 2rem; font-weight: 700; color: #1976d2; }}
  .stat .lbl {{ font-size: .85rem; color: #888; }}
</style>
</head>
<body>
<h1>TeleGen Human Validation</h1>
<div class="summary">
  <p><strong>Experiment:</strong> DeepSeek-V4-Flash LLM Injection (TeleGen) — 493/647 (76.2%)</p>
  <p><strong>Sample:</strong> 30 WV-Success + 30 WV-Failure = 60 cases (blinded, shuffled)</p>
  <p><strong>Seed:</strong> {seed}</p>
  <div class="stats">
    <div class="stat"><div class="num" id="done-count">0</div><div class="lbl">Reviewed</div></div>
    <div class="stat"><div class="num">60</div><div class="lbl">Total</div></div>
    <div class="stat"><div class="num" id="pct">0%</div><div class="lbl">Progress</div></div>
  </div>
</div>
<div class="grid" id="case-grid">
{cards}
</div>
<script>
  // Track progress via localStorage
  function getProgress() {{
    try {{ return JSON.parse(localStorage.getItem('telegen_review_progress') || '{{}}'); }}
    catch(e) {{ return {{}}; }}
  }}
  function refresh() {{
    const p = getProgress();
    let done = 0;
    document.querySelectorAll('.card').forEach(c => {{
      const id = c.dataset.caseId;
      if (p[id] && p[id].verdict) {{
        c.classList.add('done');
        c.classList.remove('pending');
        c.querySelector('.status').textContent = 'Reviewed: ' + p[id].verdict;
        done++;
      }}
    }});
    document.getElementById('done-count').textContent = done;
    document.getElementById('pct').textContent = Math.round(done/60*100) + '%';
  }}
  // Save verdict when returning from review page
  window.addEventListener('focus', refresh);
  refresh();
</script>
</body>
</html>
"""

REVIEW_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Case {case_id}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 0; background: #f5f5f5; color: #333; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 1.5rem; }}
  .nav {{ display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 1.5rem; background: #fff; border-radius: 8px;
          padding: .75rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  .nav a {{ text-decoration: none; color: #1976d2; font-weight: 500; }}
  .nav a:disabled {{ color: #ccc; pointer-events: none; }}
  .nav .case-id {{ font-weight: 700; font-size: 1.2rem; }}
  section {{ background: #fff; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem;
             box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  h2 {{ margin-top: 0; font-size: 1.25rem; color: #222; }}
  .task-desc {{ font-size: 1.05rem; line-height: 1.6; }}
  .expected {{ background: #f0f7ff; padding: .75rem 1rem; border-radius: 6px;
               border-left: 4px solid #1976d2; margin-top: .5rem; }}
  .trajectory-step {{ border-left: 3px solid #e0e0e0; padding-left: 1rem; margin-bottom: 1rem; }}
  .trajectory-step .step-num {{ font-weight: 700; color: #1976d2; }}
  .trajectory-step .thought {{ color: #555; margin: .25rem 0; }}
  .trajectory-step .action {{ color: #333; font-weight: 500; }}
  .screenshots {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .5rem; }}
  .screenshots img {{ width: 200px; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; }}
  .final-screenshot img {{ width: 100%; max-width: 700px; border: 1px solid #ddd; border-radius: 6px; }}
  .annotate {{ background: #fffde7; border-radius: 8px; padding: 1.5rem;
               box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  .annotate table {{ width: 100%; border-collapse: collapse; }}
  .annotate td {{ padding: .4rem .6rem; border-bottom: 1px solid #eee; }}
  .annotate td:first-child {{ font-weight: 600; width: 180px; }}
  .annotate input, .annotate select, .annotate textarea {{ width: 100%; padding: .3rem;
       border: 1px solid #ccc; border-radius: 4px; font-size: .95rem; }}
  .reveal {{ margin-top: 1rem; }}
  .reveal summary {{ cursor: pointer; font-weight: 600; color: #d32f2f; padding: .5rem; }}
  .reveal-content {{ padding: 1rem; background: #fff3e0; border-radius: 6px; margin-top: .5rem; }}
  .source-link {{ margin-top: .5rem; font-size: .9rem; }}
  .source-link a {{ color: #666; text-decoration: none; }}
  .copy-hint {{ font-size: .85rem; color: #888; margin-top: .5rem; }}
  .modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0;
           width: 100%; height: 100%; background: rgba(0,0,0,.8); }}
  .modal img {{ max-width: 95%; max-height: 95%; margin: auto; display: block; padding-top: 2rem; }}
  .modal:target {{ display: block; }}
</style>
</head>
<body>
<div class="container">
  <div class="nav">
    <a href="{prev_html}" {prev_disabled}>&larr; Previous</a>
    <span class="case-id">{case_id}</span>
    <a href="{next_html}" {next_disabled}>Next &rarr;</a>
  </div>
  <div style="text-align:center;margin-bottom:1rem;"><a href="../index.html">&larr; Back to all cases</a></div>

  <section>
    <h2>Task Description</h2>
    <div class="task-desc">{task_description}</div>
    <div class="expected"><strong>Expected result:</strong> {expected_result}</div>
    <div style="margin-top:.5rem;font-size:.85rem;color:#888;">Category: {task_category}</div>
  </section>

  <section>
    <h2>Trajectory</h2>
    {trajectory_html}
  </section>

  <section>
    <h2>Screenshot Gallery</h2>
    <div class="screenshots">
      {gallery_html}
    </div>
  </section>

  <section>
    <h2>Final Screenshot</h2>
    <div class="final-screenshot">
      {final_screenshot_html}
    </div>
  </section>

  <section>
    <h2>Final State</h2>
    {final_state_html}
  </section>

  <section class="annotate">
    <h2>Annotation</h2>
    <p>Fill in the fields below, then copy the row into <code>annotation_template.csv</code>.</p>
    <table>
      <tr><td>case_id</td><td>{case_id}</td></tr>
      <tr><td>project_id</td><td><em>hidden (see unblinded CSV)</em></td></tr>
      <tr><td>task_id</td><td><em>hidden (see unblinded CSV)</em></td></tr>
      <tr><td>task_category</td><td>{task_category}</td></tr>
      <tr><td>human_verdict</td><td>
        <select id="human_verdict">
          <option value="">-- Select --</option>
          <option value="Success">Success</option>
          <option value="Failure">Failure</option>
          <option value="Unclear">Unclear</option>
        </select>
      </td></tr>
      <tr><td>human_confidence</td><td>
        <select id="human_confidence">
          <option value="">-- Select --</option>
          <option value="High">High</option>
          <option value="Medium">Medium</option>
          <option value="Low">Low</option>
        </select>
      </td></tr>
      <tr><td>trajectory_valid</td><td>
        <select id="trajectory_valid">
          <option value="">-- Select --</option>
          <option value="Yes">Yes</option>
          <option value="No">No</option>
          <option value="Unclear">Unclear</option>
        </select>
      </td></tr>
      <tr><td>failure_type</td><td>
        <select id="failure_type">
          <option value="Not applicable">Not applicable</option>
          <option value="Application failure">Application failure</option>
          <option value="Agent trajectory failure">Agent trajectory failure</option>
          <option value="Timing/loading failure">Timing/loading failure</option>
          <option value="Judge error">Judge error</option>
          <option value="Infrastructure failure">Infrastructure failure</option>
          <option value="Insufficient evidence">Insufficient evidence</option>
          <option value="Other">Other</option>
        </select>
      </td></tr>
      <tr><td>evidence_step</td><td><input type="text" id="evidence_step" placeholder="e.g. step 3"></td></tr>
      <tr><td>evidence_screenshot</td><td><input type="text" id="evidence_screenshot" placeholder="e.g. final.png"></td></tr>
      <tr><td>annotation_reason</td><td><textarea id="annotation_reason" rows="3" placeholder="Evidence-based explanation..."></textarea></td></tr>
      <tr><td>annotator_id</td><td><input type="text" id="annotator_id" placeholder="your ID"></td></tr>
      <tr><td>needs_second_review</td><td>
        <select id="needs_second_review">
          <option value="No">No</option>
          <option value="Yes">Yes</option>
        </select>
      </td></tr>
      <tr><td>adjudicated_verdict</td><td><input type="text" id="adjudicated_verdict" placeholder="leave empty"></td></tr>
      <tr><td>adjudication_notes</td><td><input type="text" id="adjudication_notes" placeholder="leave empty"></td></tr>
    </table>
    <div class="copy-hint">After filling, save your verdict to track progress:
      <button onclick="saveProgress()" style="padding:.3rem .8rem;cursor:pointer;">Save verdict locally</button>
      <span id="saved-msg" style="color:green;display:none;">Saved!</span>
    </div>
  </section>

  <details class="reveal">
    <summary>Reveal original WebVoyager judgment</summary>
    <div class="reveal-content">
      <p><strong>WV Verdict:</strong> {wv_verdict}</p>
      <p><strong>WV Answer:</strong> {wv_answer}</p>
      <p><strong>WV Evaluator Response:</strong></p>
      <pre style="white-space:pre-wrap;font-size:.9rem;">{wv_evaluator_response}</pre>
    </div>
  </details>

  <div class="source-link">
    <details>
      <summary>Application source directory (only if needed)</summary>
      <a href="{source_link}">{source_path}</a>
    </details>
  </div>
</div>

<div class="modal" id="img-modal" onclick="this.style.display='none'">
  <img id="modal-img" src="">
</div>

<script>
  function showImg(src) {{
    document.getElementById('modal-img').src = src;
    document.getElementById('img-modal').style.display = 'block';
  }}
  function saveProgress() {{
    const verdict = document.getElementById('human_verdict').value;
    if (!verdict) {{ alert('Please select a verdict first.'); return; }}
    const p = JSON.parse(localStorage.getItem('telegen_review_progress') || '{{}}');
    p['{case_id}'] = {{ verdict: verdict }};
    localStorage.setItem('telegen_review_progress', JSON.stringify(p));
    document.getElementById('saved-msg').style.display = 'inline';
    setTimeout(() => document.getElementById('saved-msg').style.display = 'none', 2000);
  }}
</script>
</body>
</html>
"""


def generate_review_html(
    case_id: str,
    case: dict,
    case_num: int,
    total_cases: int,
    blind: bool,
    workspace: Path,
    case_dir: Path,
) -> str:
    """Generate the review.html for a single case."""
    prev_num = max(1, case_num - 1)
    next_num = min(total_cases, case_num + 1)
    prev_html = f"../case_{prev_num:03d}/review.html"
    next_html = f"../case_{next_num:03d}/review.html"
    prev_disabled = "" if case_num > 1 else 'style="visibility:hidden"'
    next_disabled = "" if case_num < total_cases else 'style="visibility:hidden"'

    # Task description and expected result
    task_desc = html.escape(case["task_description"])
    expected = html.escape(case["expected_result"])
    task_cat = html.escape(case["task_category"])

    # Trajectory
    steps = parse_trajectory(case["trajectory_path"])
    if steps:
        traj_parts = []
        for s in steps:
            screenshot_link = ""
            if s["screenshot"]:
                screenshot_link = f' <em style="color:#888;">[{html.escape(s["screenshot"])}]</em>'
            traj_parts.append(
                f'<div class="trajectory-step">'
                f'<span class="step-num">Step {s["step"]}</span>{screenshot_link}'
                f'<div class="thought">{html.escape(s["thought"])}</div>'
                f'<div class="action">{html.escape(s["action"])}</div>'
                f'</div>'
            )
        trajectory_html = "\n".join(traj_parts)
    else:
        trajectory_html = "<p>Not available in stored experiment artifacts.</p>"

    # Screenshot gallery
    screenshots = case.get("screenshot_paths", [])
    if screenshots:
        gallery_parts = []
        for i, ss in enumerate(screenshots):
            ss_name = os.path.basename(ss)
            ss_rel = f"screenshots/{ss_name}"
            gallery_parts.append(
                f'<img src="{ss_rel}" alt="Step {i+1}" title="Step {i+1}: {ss_name}" onclick="showImg(this.src)">'
            )
        gallery_html = "\n".join(gallery_parts)
    else:
        gallery_html = "<p>Not available in stored experiment artifacts.</p>"

    # Final screenshot
    final_ss = case.get("final_screenshot_path", "")
    if final_ss:
        final_name = os.path.basename(final_ss)
        final_html = f'<img src="screenshots/{final_name}" alt="Final screenshot" onclick="showImg(this.src)">'
    else:
        final_html = "<p>Not available in stored experiment artifacts.</p>"

    # Final state
    final_state_parts = []
    if final_ss:
        final_state_parts.append(f"<p><strong>Final screenshot:</strong> {os.path.basename(final_ss)}</p>")
    else:
        final_state_parts.append("<p><strong>Final screenshot:</strong> Not available in stored experiment artifacts.</p>")
    final_state_html = "\n".join(final_state_parts)

    # WV verdict (in reveal section)
    wv_verdict = case["wv_verdict"]
    wv_answer = html.escape(case.get("wv_answer", "") or "Not available.")
    wv_eval = html.escape(case.get("wv_evaluator_response", "") or "Not available.")

    # Source link
    source_path = case.get("app_source_path", "")
    source_link = "source_paths.md"

    return REVIEW_HTML_TEMPLATE.format(
        case_id=case_id,
        prev_html=prev_html,
        next_html=next_html,
        prev_disabled=prev_disabled,
        next_disabled=next_disabled,
        task_description=task_desc,
        expected_result=expected,
        task_category=task_cat,
        trajectory_html=trajectory_html,
        gallery_html=gallery_html,
        final_screenshot_html=final_html,
        final_state_html=final_state_html,
        wv_verdict=wv_verdict,
        wv_answer=wv_answer,
        wv_evaluator_response=wv_eval,
        source_link=source_link,
        source_path=html.escape(source_path),
    )


# ── Package builder ────────────────────────────────────────────────

def build_package(
    workspace: Path,
    output: Path,
    candidates: List[dict],
    success_selected: List[dict],
    failure_selected: List[dict],
    sampling_info: dict,
    seed: int,
    blind: bool,
    copy_all: bool,
    errors: List[str],
) -> None:
    """Build the complete review package."""
    if output.exists():
        sys.exit(
            f"ERROR: Output directory {output} already exists. "
            "Use --force to overwrite."
        )
    output.mkdir(parents=True)

    all_selected = success_selected + failure_selected
    rng = random.Random(seed + 1)  # Different seed for shuffling
    rng.shuffle(all_selected)

    # Assign neutral case IDs
    for i, case in enumerate(all_selected):
        case["_case_id"] = f"case_{i+1:03d}"
        case["_case_num"] = i + 1

    total_cases = len(all_selected)

    # ── Save full candidate manifest ────────────────────────────────
    # CSV
    manifest_csv = output / "candidate_manifest.csv"
    manifest_fields = [
        "project_id", "task_id", "task_idx", "task_description",
        "expected_result", "task_category", "task_subcategories",
        "wv_verdict", "wv_status_raw", "wv_answer",
        "trajectory_path", "screenshot_count", "final_screenshot_path",
        "app_source_path", "eval_source_path",
    ]
    with open(manifest_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=manifest_fields, extrasaction="ignore")
        writer.writeheader()
        for c in candidates:
            row = dict(c)
            row["screenshot_count"] = len(c.get("screenshot_paths", []))
            writer.writerow(row)

    # JSONL
    manifest_jsonl = output / "candidate_manifest.jsonl"
    with open(manifest_jsonl, "w", encoding="utf-8") as f:
        for c in candidates:
            row = {k: v for k, v in c.items() if not k.startswith("_")}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ── Save selected cases (blinded and unblinded) ────────────────
    blinded_csv = output / "selected_cases_blinded.csv"
    unblinded_csv = output / "selected_cases_unblinded.csv"

    blinded_fields = [
        "case_id", "task_description", "expected_result", "task_category",
        "task_subcategories", "screenshot_count", "has_trajectory",
        "has_final_screenshot",
    ]
    unblinded_fields = [
        "case_id", "project_id", "task_id", "task_description",
        "expected_result", "task_category", "task_subcategories",
        "wv_verdict", "screenshot_count", "has_trajectory",
        "has_final_screenshot", "trajectory_path", "final_screenshot_path",
        "app_source_path", "eval_source_path",
    ]

    with open(blinded_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=blinded_fields, extrasaction="ignore")
        writer.writeheader()
        for c in all_selected:
            row = {
                "case_id": c["_case_id"],
                "task_description": c["task_description"],
                "expected_result": c["expected_result"],
                "task_category": c["task_category"],
                "task_subcategories": c["task_subcategories"],
                "screenshot_count": len(c.get("screenshot_paths", [])),
                "has_trajectory": os.path.exists(c["trajectory_path"]) if c["trajectory_path"] else False,
                "has_final_screenshot": bool(c.get("final_screenshot_path")),
            }
            writer.writerow(row)

    with open(unblinded_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=unblinded_fields, extrasaction="ignore")
        writer.writeheader()
        for c in all_selected:
            row = {
                "case_id": c["_case_id"],
                "project_id": c["project_id"],
                "task_id": c["task_id"],
                "task_description": c["task_description"],
                "expected_result": c["expected_result"],
                "task_category": c["task_category"],
                "task_subcategories": c["task_subcategories"],
                "wv_verdict": c["wv_verdict"],
                "screenshot_count": len(c.get("screenshot_paths", [])),
                "has_trajectory": os.path.exists(c["trajectory_path"]) if c["trajectory_path"] else False,
                "has_final_screenshot": bool(c.get("final_screenshot_path")),
                "trajectory_path": c["trajectory_path"],
                "final_screenshot_path": c.get("final_screenshot_path", ""),
                "app_source_path": c["app_source_path"],
                "eval_source_path": c["eval_source_path"],
            }
            writer.writerow(row)

    # ── Annotation template CSV ────────────────────────────────────
    ann_csv = output / "annotation_template.csv"
    ann_fields = [
        "case_id", "project_id", "task_id", "task_category",
        "human_verdict", "human_confidence", "trajectory_valid",
        "failure_type", "evidence_step", "evidence_screenshot",
        "annotation_reason", "annotator_id", "annotation_timestamp",
        "needs_second_review", "adjudicated_verdict", "adjudication_notes",
    ]
    with open(ann_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ann_fields)
        writer.writeheader()
        for c in all_selected:
            writer.writerow({
                "case_id": c["_case_id"],
                "project_id": c["project_id"] if not blind else "",
                "task_id": c["task_id"] if not blind else "",
                "task_category": c["task_category"],
                "human_verdict": "",
                "human_confidence": "",
                "trajectory_valid": "",
                "failure_type": "",
                "evidence_step": "",
                "evidence_screenshot": "",
                "annotation_reason": "",
                "annotator_id": "",
                "annotation_timestamp": "",
                "needs_second_review": "",
                "adjudicated_verdict": "",
                "adjudication_notes": "",
            })

    # ── Config JSON ────────────────────────────────────────────────
    config = {
        "random_seed": seed,
        "num_success": len(success_selected),
        "num_failure": len(failure_selected),
        "total_cases": total_cases,
        "blind": blind,
        "experiment": "DeepSeek-V4-Flash LLM Injection (TeleGen)",
        "paper_result": "493/647 (76.2%)",
        "source_csv": BASELINE_CSV_CSV,
        "source_summary": SUMMARY_JSON,
        "source_tasks": TASKS_JSONL,
        "expected_success": EXPECTED_SUCCESS,
        "expected_total": EXPECTED_TOTAL,
    }
    (output / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )

    # ── Per-case directories ───────────────────────────────────────
    for case in all_selected:
        case_id = case["_case_id"]
        case_dir = output / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        ss_dir = case_dir / "screenshots"
        ss_dir.mkdir(exist_ok=True)

        # case_metadata.json
        meta = {
            "case_id": case_id,
            "project_id": case["project_id"],
            "task_id": case["task_id"],
            "task_description": case["task_description"],
            "expected_result": case["expected_result"],
            "task_category": case["task_category"],
            "task_subcategories": case["task_subcategories"],
            "wv_verdict": case["wv_verdict"],
            "wv_answer": case.get("wv_answer", ""),
            "wv_evaluator_response": case.get("wv_evaluator_response", ""),
            "trajectory_path": case["trajectory_path"],
            "screenshot_paths": case.get("screenshot_paths", []),
            "final_screenshot_path": case.get("final_screenshot_path", ""),
            "app_source_path": case["app_source_path"],
            "eval_source_path": case["eval_source_path"],
        }
        (case_dir / "case_metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # task.md (blinded)
        task_md = f"""# {case_id}

## Task Instruction

{case['task_description']}

## Expected Result

{case['expected_result']}

## Task Category

{case['task_category']}

{f"Subcategories: {case['task_subcategories']}" if case['task_subcategories'] else ""}

---
*Project ID and task ID are recorded in the unblinded manifest for traceability.*
"""
        if not blind:
            task_md += f"\n**Project:** {case['project_id']}  \n**Task:** {case['task_id']}\n"
        (case_dir / "task.md").write_text(task_md, encoding="utf-8")

        # trajectory.json (copy or symlink)
        traj_path = Path(case["trajectory_path"])
        if traj_path.exists():
            safe_symlink(traj_path, case_dir / "trajectory.json", copy=copy_all)

            # trajectory.md
            steps = parse_trajectory(case["trajectory_path"])
            traj_md_parts = [f"# Trajectory — {case_id}\n"]
            for s in steps:
                ss_note = f" | Screenshot: `{s['screenshot']}`" if s["screenshot"] else ""
                traj_md_parts.append(
                    f"## Step {s['step']}{ss_note}\n\n"
                    f"**Thought:** {s['thought']}\n\n"
                    f"**Action:** {s['action']}\n"
                )
            if not steps:
                traj_md_parts.append("Not available in stored experiment artifacts.\n")
            (case_dir / "trajectory.md").write_text(
                "\n".join(traj_md_parts), encoding="utf-8"
            )
        else:
            (case_dir / "trajectory.md").write_text(
                "Not available in stored experiment artifacts.\n", encoding="utf-8"
            )

        # Screenshots
        screenshots = case.get("screenshot_paths", [])
        for i, ss in enumerate(screenshots):
            ss_src = Path(ss)
            if ss_src.exists():
                ss_name = os.path.basename(ss)
                if i == len(screenshots) - 1:
                    dst_name = "final.png"
                else:
                    dst_name = f"step_{i+1:03d}.png"
                safe_symlink(ss_src, ss_dir / dst_name, copy=copy_all)
                # Also keep original name
                safe_symlink(ss_src, ss_dir / ss_name, copy=copy_all)

        # final_state.md
        final_ss = case.get("final_screenshot_path", "")
        final_state_md = f"""# Final State — {case_id}

## Final Screenshot

"""
        if final_ss and os.path.exists(final_ss):
            final_name = os.path.basename(final_ss)
            final_state_md += f"![Final screenshot](screenshots/final.png)\n\n"
            final_state_md += f"File: `{final_name}`\n\n"
        else:
            final_state_md += "Not available in stored experiment artifacts.\n\n"

        final_state_md += """## Final URL

Not available in stored experiment artifacts.

## Final Visible Page Text

Not available in stored experiment artifacts.

## Final DOM Summary

Not available in stored experiment artifacts.

---

<details>
<summary>Reveal WV assessment</summary>

"""
        final_state_md += f"**WV Verdict:** {case['wv_verdict']}\n\n"
        final_state_md += f"**WV Answer:** {case.get('wv_answer', 'Not available.')}\n\n"
        final_state_md += "</details>\n"
        (case_dir / "final_state.md").write_text(final_state_md, encoding="utf-8")

        # source_paths.md
        source_md = f"""# Source Paths — {case_id}

**Application source:** `{case['app_source_path']}`

**Evaluation result:** `{case['eval_source_path']}`

**Trajectory:** `{case['trajectory_path']}`

**Task directory:** `{case.get('task_dir', 'N/A')}`
"""
        (case_dir / "source_paths.md").write_text(source_md, encoding="utf-8")

        # review.html
        review_html = generate_review_html(
            case_id=case_id,
            case=case,
            case_num=case["_case_num"],
            total_cases=total_cases,
            blind=blind,
            workspace=workspace,
            case_dir=case_dir,
        )
        (case_dir / "review.html").write_text(review_html, encoding="utf-8")

    # ── Index HTML ──────────────────────────────────────────────────
    cards_parts = []
    for case in all_selected:
        case_id = case["_case_id"]
        cards_parts.append(
            f'<a class="card pending" href="cases/{case_id}/review.html" data-case-id="{case_id}">'
            f'<div class="id">{case_id}</div>'
            f'<div class="status">Not yet reviewed</div>'
            f'</a>'
        )
    index_html = INDEX_HTML_TEMPLATE.format(
        seed=seed,
        cards="\n".join(cards_parts),
    )
    (output / "index.html").write_text(index_html, encoding="utf-8")

    # ── README ──────────────────────────────────────────────────────
    readme = f"""# TeleGen Human Validation Package

## Overview

This package contains a blinded human-review interface for validating
WebVoyager judgments on the final TeleGen outputs.

- **Experiment:** DeepSeek-V4-Flash LLM Injection (TeleGen)
- **Paper result:** 493/647 (76.2%)
- **Sample:** 30 WV-Success + 30 WV-Failure = 60 cases
- **Seed:** {seed}
- **Blinded:** {blind}

## How to Review

1. Open `index.html` in a web browser.
2. Click any case to begin reviewing.
3. Read the task description, expected result, trajectory, and screenshots.
4. Fill in the annotation form (or copy the fields into `annotation_template.csv`).
5. Use the "Reveal original WebVoyager judgment" section only after annotating.

## Files

- `index.html` — Main review interface listing all 60 cases.
- `cases/case_XXX/review.html` — Per-case review page.
- `cases/case_XXX/task.md` — Task description and expected result.
- `cases/case_XXX/trajectory.md` — Agent trajectory in chronological order.
- `cases/case_XXX/screenshots/` — Screenshots (symlinked to originals).
- `cases/case_XXX/final_state.md` — Final screenshot and state.
- `annotation_template.csv` — Fill this in with your annotations.
- `selected_cases_blinded.csv` — Blinded case list (no WV verdict).
- `selected_cases_unblinded.csv` — Unblinded case list (includes WV verdict).
- `candidate_manifest.csv` / `.jsonl` — Full candidate manifest (all 647 tasks).
- `sampling_report.md` — Sampling details and statistics.
- `annotation_guidelines.md` — Review guidelines.
- `config.json` — Configuration.

## Post-Annotation Analysis

```bash
python scripts/analyze_human_annotations.py \\
    --annotations human_validation_telegen/annotation_template.csv \\
    --unblinded-manifest human_validation_telegen/selected_cases_unblinded.csv
```
"""
    (output / "README.md").write_text(readme, encoding="utf-8")

    # ── Annotation guidelines ───────────────────────────────────────
    guidelines = """# Annotation Guidelines

## Purpose

You are validating whether WebVoyager's Success/Failure judgment is correct
for each task, based on the saved execution evidence.

## How to Judge

### Success
- The required user-visible result was achieved.
- Minor cosmetic differences do not invalidate the task unless appearance is
  part of the expected result.

### Failure
- The required result was not achieved.
- The trajectory ended before completing the task.
- The page entered an incorrect state.
- Required content or functionality was absent.

### Unclear
- The stored screenshots or trajectory are insufficient.
- The final state is ambiguous.
- Required evidence is missing.
- Infrastructure failure prevents a reliable judgment.

## Distinguishing Failure Types

- **Application failure**: The app has a bug or missing feature.
- **Agent trajectory failure**: The app works but the agent navigated incorrectly.
- **Timing/loading failure**: The page didn't load in time.
- **Judge error**: WebVoyager's verdict contradicts the visible evidence.
- **Infrastructure failure**: Server crashed, port conflict, etc.
- **Insufficient evidence**: Can't tell from available artifacts.

## Key Rules

1. Judge based on the **saved execution evidence** (screenshots + trajectory),
   not on what the app "should" do.
2. **Do not infer success** solely from WebVoyager's textual explanation if
   the visible evidence contradicts it.
3. The **original WV verdict is hidden** — reveal it only after you have
   recorded your own judgment.
4. Provide an **evidence-based reason** for every annotation (not just
   "correct" or "incorrect").
5. Reference the specific step or screenshot that supports your judgment.

## Annotation Fields

| Field | Allowed Values |
|-------|---------------|
| human_verdict | Success / Failure / Unclear |
| human_confidence | High / Medium / Low |
| trajectory_valid | Yes / No / Unclear |
| failure_type | Application failure / Agent trajectory failure / Timing/loading failure / Judge error / Infrastructure failure / Insufficient evidence / Not applicable / Other |
| evidence_step | Step number (e.g. "step 3") |
| evidence_screenshot | Screenshot filename (e.g. "final.png") |
| annotation_reason | Evidence-based explanation |
| annotator_id | Your identifier |
| needs_second_review | Yes / No |
"""
    (output / "annotation_guidelines.md").write_text(guidelines, encoding="utf-8")

    # ── Sampling report ────────────────────────────────────────────
    all_cats = Counter(c["task_category"] for c in candidates)
    succ_cats = Counter(c["task_category"] for c in candidates if c["wv_verdict"] == "Success")
    fail_cats = Counter(c["task_category"] for c in candidates if c["wv_verdict"] == "Failure")
    selected_cats = Counter(c["task_category"] for c in all_selected)
    selected_projects = Counter(c["project_id"] for c in all_selected)

    report = f"""# Sampling Report

## Experiment Source

- **Experiment:** DeepSeek-V4-Flash LLM Injection (TeleGen)
- **Source CSV:** `{BASELINE_CSV_CSV}`
- **Source Summary:** `{SUMMARY_JSON}`
- **Paper result:** 493/647 (76.2%)
- **Verified:** 493 SUCCESS + 154 FAILURE = 647 total ✓

## Sampling Configuration

- **Random seed:** {seed}
- **Requested success:** {len(success_selected)}
- **Requested failure:** {len(failure_selected)}
- **Total selected:** {total_cases}
- **Algorithm:** Deterministic stratified random sampling with project constraint

## Sampling Algorithm

1. Separate candidates into success (493) and failure (154) strata.
2. Within each stratum, compute proportional category targets.
3. Sample within each category, preferring at most 1 task per project.
4. If insufficient, relax to at most 2 tasks per project.
5. Shuffle the final 60 cases with a separate RNG state (seed + 1).
6. Assign neutral IDs: case_001 … case_060.

## Category Distribution (All Candidates)

| Category | Success | Failure | Total |
|----------|---------|---------|-------|
"""
    for cat in sorted(all_cats.keys()):
        report += f"| {cat} | {succ_cats.get(cat, 0)} | {fail_cats.get(cat, 0)} | {all_cats[cat]} |\n"

    report += f"""
## Category Distribution (Selected)

| Category | Count |
|----------|-------|
"""
    for cat in sorted(selected_cats.keys()):
        report += f"| {cat} | {selected_cats[cat]} |\n"

    report += f"""
## Project Distribution (Selected)

- **Distinct projects:** {len(selected_projects)}
- **Max tasks per project:** {max(selected_projects.values()) if selected_projects else 0}

| Project | Tasks Selected |
|---------|---------------|
"""
    for proj in sorted(selected_projects.keys()):
        report += f"| {proj} | {selected_projects[proj]} |\n"

    report += f"""
## Sampling Details

### Success stratum
- Pool size: {sampling_info['success']['pool_size']}
- Selected: {sampling_info['success']['selected']}
- Max per project: {sampling_info['success']['max_per_project']}
- Projects with 2 tasks: {sampling_info['success']['projects_with_2_tasks'] or 'None'}

### Failure stratum
- Pool size: {sampling_info['failure']['pool_size']}
- Selected: {sampling_info['failure']['selected']}
- Max per project: {sampling_info['failure']['max_per_project']}
- Projects with 2 tasks: {sampling_info['failure']['projects_with_2_tasks'] or 'None'}

## Exclusions

"""
    if errors:
        report += "The following issues were encountered during manifest building:\n\n"
        for e in errors[:20]:
            report += f"- {e}\n"
        if len(errors) > 20:
            report += f"- ... and {len(errors) - 20} more\n"
    else:
        report += "No exclusions. All 647 candidates had valid verdicts and task metadata.\n"

    report += f"""
## Validation Summary

- Candidate success count: {sum(1 for c in candidates if c['wv_verdict'] == 'Success')}
- Candidate failure count: {sum(1 for c in candidates if c['wv_verdict'] == 'Failure')}
- Selected success count: {len(success_selected)}
- Selected failure count: {len(failure_selected)}
- Total selected: {total_cases}
- Distinct projects: {len(selected_projects)}
- Cases with complete trajectories: {sum(1 for c in all_selected if os.path.exists(c['trajectory_path']))}
- Cases with screenshots: {sum(1 for c in all_selected if c.get('screenshot_paths'))}
- Cases with final screenshots: {sum(1 for c in all_selected if c.get('final_screenshot_path'))}
- Cases with missing artifacts: {sum(1 for c in all_selected if not c.get('screenshot_paths') or not os.path.exists(c['trajectory_path']))}
"""
    (output / "sampling_report.md").write_text(report, encoding="utf-8")

    # ── Scripts directory (copy analysis script) ────────────────────
    scripts_dir = output / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    # ── Analysis directory ──────────────────────────────────────────
    (output / "analysis").mkdir(exist_ok=True)

    # ── Print final summary ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("HUMAN VALIDATION PACKAGE BUILT")
    print("=" * 60)
    print(f"Experiment source: {workspace}")
    print(f"  CSV: {BASELINE_CSV_CSV}")
    print(f"  Summary: {SUMMARY_JSON}")
    print(f"  Paper result: 493/647 (76.2%) ✓")
    print(f"Sampling seed: {seed}")
    print(f"Selected WV-success cases: {len(success_selected)}")
    print(f"Selected WV-failure cases: {len(failure_selected)}")
    print(f"Distinct projects: {len(selected_projects)}")
    print(f"Category coverage: {len(selected_cats)} categories")
    missing_ss = sum(1 for c in all_selected if not c.get('screenshot_paths'))
    missing_traj = sum(1 for c in all_selected if not os.path.exists(c['trajectory_path']))
    print(f"Cases missing screenshots: {missing_ss}")
    print(f"Cases missing trajectories: {missing_traj}")
    print(f"Output directory: {output}")
    print(f"Index HTML: {output / 'index.html'}")
    print(f"Annotation template: {output / 'annotation_template.csv'}")
    print()
    print("Post-annotation analysis command:")
    print(f"  python scripts/analyze_human_annotations.py \\")
    print(f"      --annotations {output}/annotation_template.csv \\")
    print(f"      --unblinded-manifest {output}/selected_cases_unblinded.csv")
    print("=" * 60)


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build human validation package for TeleGen WebVoyager judgments"
    )
    parser.add_argument(
        "--experiment-root",
        default=".",
        help="Path to the Fullstack-WebGen-main workspace root.",
    )
    parser.add_argument(
        "--output",
        default="human_validation_telegen",
        help="Output directory for the validation package.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for deterministic sampling.",
    )
    parser.add_argument(
        "--num-success",
        type=int,
        default=30,
        help="Number of WV-success cases to sample.",
    )
    parser.add_argument(
        "--num-failure",
        type=int,
        default=30,
        help="Number of WV-failure cases to sample.",
    )
    parser.add_argument(
        "--blind",
        action="store_true",
        default=True,
        help="Hide WV verdict in review interface (default: True).",
    )
    parser.add_argument(
        "--copy-all",
        action="store_true",
        help="Copy all files instead of symlinking (portable package).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output directory.",
    )

    args = parser.parse_args()

    workspace = Path(args.experiment_root).resolve()
    output = Path(args.output).resolve()

    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = workspace

    if not workspace.exists():
        sys.exit(f"ERROR: Workspace not found: {workspace}")

    # Handle --force
    if output.exists():
        if not args.force:
            sys.exit(
                f"ERROR: Output directory {output} already exists. "
                "Use --force to overwrite."
            )
        shutil.rmtree(output)

    # 1. Verify 493/647
    print("Step 1: Verifying TeleGen 493/647 result...")
    summary = verify_493_647(workspace)
    print(f"  ✓ Confirmed: {summary['logged_total']}/{summary['total_tasks']} ({summary['logged_rate']}%)")

    # 2. Load task definitions
    print("Step 2: Loading task definitions...")
    tasks_data = load_tasks(workspace)
    print(f"  ✓ Loaded {len(tasks_data)} projects")

    # 3. Load project summaries
    print("Step 3: Loading project summaries...")
    project_rows = load_project_summaries(workspace)
    print(f"  ✓ Loaded {len(project_rows)} projects")

    # 4. Build candidate manifest
    print("Step 4: Building candidate manifest...")
    candidates, errors = build_candidate_manifest(workspace, project_rows, tasks_data)
    succ_count = sum(1 for c in candidates if c["wv_verdict"] == "Success")
    fail_count = sum(1 for c in candidates if c["wv_verdict"] == "Failure")
    print(f"  ✓ {len(candidates)} candidates ({succ_count} success, {fail_count} failure)")
    if errors:
        print(f"  ⚠ {len(errors)} issues encountered (see sampling_report.md)")

    # 5. Validate candidate counts
    if succ_count < args.num_success:
        sys.exit(f"ERROR: Only {succ_count} success candidates, need {args.num_success}")
    if fail_count < args.num_failure:
        sys.exit(f"ERROR: Only {fail_count} failure candidates, need {args.num_failure}")

    # 6. Stratified sampling
    print(f"Step 5: Stratified sampling (seed={args.seed})...")
    success_selected, failure_selected, sampling_info = stratified_sample(
        candidates, args.num_success, args.num_failure, args.seed
    )
    print(f"  ✓ Selected {len(success_selected)} success + {len(failure_selected)} failure = {len(success_selected) + len(failure_selected)}")

    # 7. Check for duplicates
    all_sel = success_selected + failure_selected
    seen = set()
    for c in all_sel:
        key = (c["project_id"], c["task_id"])
        if key in seen:
            sys.exit(f"ERROR: Duplicate project/task selected: {key}")
        seen.add(key)

    # 8. Validate metadata
    for c in all_sel:
        if not c["task_description"]:
            sys.exit(f"ERROR: Missing task description for {c['project_id']}/{c['task_id']}")
        if not c["expected_result"]:
            sys.exit(f"ERROR: Missing expected result for {c['project_id']}/{c['task_id']}")

    # 9. Build package
    print("Step 6: Building review package...")
    build_package(
        workspace=workspace,
        output=output,
        candidates=candidates,
        success_selected=success_selected,
        failure_selected=failure_selected,
        sampling_info=sampling_info,
        seed=args.seed,
        blind=args.blind,
        copy_all=args.copy_all,
        errors=errors,
    )

    # 10. Final validation
    print("\nStep 7: Validating package...")
    # Check blinded manifest doesn't expose verdict
    blinded_csv = output / "selected_cases_blinded.csv"
    with open(blinded_csv) as f:
        header = f.readline()
        if "verdict" in header.lower():
            sys.exit("ERROR: Blinded CSV contains verdict column!")
    print("  ✓ Blinded CSV does not expose WV verdict")

    # Check all case directories exist
    for i in range(1, 61):
        case_dir = output / "cases" / f"case_{i:03d}"
        if not case_dir.exists():
            sys.exit(f"ERROR: Missing case directory: case_{i:03d}")
    print("  ✓ All 60 case directories present")

    print("\nDone! Open the review interface:")
    print(f"  {output / 'index.html'}")


if __name__ == "__main__":
    main()
