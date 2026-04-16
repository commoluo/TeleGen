#!/usr/bin/env python3
"""
analyze_repair_results.py
=========================
生成 OH 修复效果分析报告（HTML）。

对比每个项目的 v1 vs v2 WebVoyager pass rate，展示：
  - 逐任务成败对比
  - 改进/退步任务的具体 WV 交互日志
  - OH 修改摘要（openhands_repair_stdout.log）
  - git diff（OH 对代码做了哪些改动）
  - Telemetry brief 中已知错误 → 修复情况

用法:
  python3 openhands_integration/analyze_repair_results.py \\
      --run-dir batch_runs/run_20260401_213830 \\
      --output analysis_report.html \\
      [--projects 000001-000030]   # 可选，逗号或范围，默认全部

"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Verdict extraction
# ---------------------------------------------------------------------------

def _extract_verdict(msgs: list) -> Tuple[str, str]:
    """Return (verdict, last_assistant_text) from interact_messages list.

    Matches the exact logic of _count_v1_passes in optimize_batch_results.py:
    - Iterates messages in reverse, skipping non-assistant and no-ANSWER; messages
    - Returns UNKNOWN (not counted as YES) when no assistant message has ANSWER;
    """
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        content = re.sub(r"<think>.*?</think>", "", m.get("content", ""), flags=re.DOTALL)
        if "ANSWER;" not in content:
            continue  # skip, look for earlier assistant message with ANSWER;
        answer_text = content[content.find("ANSWER;") + 7:].strip()
        first = answer_text.split()[0].strip(".,;:").upper() if answer_text.split() else ""
        if first == "YES":
            return "YES", content.strip()
        if first == "NO":
            return "NO", content.strip()
        snippet = answer_text[:120].upper()
        if re.search(r"\bYES\b", snippet):
            return "YES", content.strip()
        if re.search(r"\bNO\b", snippet):
            return "NO", content.strip()
        return "YES", content.strip()  # ANSWER; found but no explicit YES/NO → default YES
    return "UNKNOWN", ""  # no assistant message with ANSWER; found


def _task_short_name(task_dir_name: str) -> str:
    """task000031--3 → t3"""
    m = re.search(r"--(\d+)$", task_dir_name)
    return f"t{m.group(1)}" if m else task_dir_name


def load_task_verdicts(wv_dir: Path) -> Dict[str, Tuple[str, str]]:
    """Return {task_dir_name: (verdict, last_msg)} for all tasks in wv_dir."""
    results = {}
    if not wv_dir.exists():
        return results
    for task_dir in sorted(wv_dir.iterdir()):
        if not task_dir.is_dir() or not task_dir.name.startswith("task"):
            continue
        msg_file = task_dir / "interact_messages.json"
        if not msg_file.exists():
            results[task_dir.name] = ("UNKNOWN", "no interact_messages.json")
            continue
        try:
            msgs = json.loads(msg_file.read_text(encoding="utf-8", errors="ignore"))
            verdict, txt = _extract_verdict(msgs)
            results[task_dir.name] = (verdict, txt)
        except Exception as e:
            results[task_dir.name] = ("UNKNOWN", str(e))
    return results


# ---------------------------------------------------------------------------
# OH log parsing
# ---------------------------------------------------------------------------

def extract_oh_summary(stdout_log: Path) -> str:
    """Extract the CONVERSATION SUMMARY block from openhands repr stdout log."""
    if not stdout_log.exists():
        return "(log not found)"
    text = stdout_log.read_text(encoding="utf-8", errors="ignore")
    # Find the summary block
    marker = "CONVERSATION SUMMARY"
    idx = text.find(marker)
    if idx == -1:
        # Try to get last 2000 chars as fallback
        return text[-2000:].strip() if text else "(empty log)"
    return text[idx:idx + 4000].strip()


# ---------------------------------------------------------------------------
# Git diff
# ---------------------------------------------------------------------------

def get_git_diff(v2_dir: Path) -> str:
    """Get unstaged changes in v2_experiment dir (OH edits are unstaged)."""
    if not v2_dir.exists():
        return "(dir not found)"
    # exclude node_modules and log files
    try:
        result = subprocess.run(
            ["git", "diff", "--", "frontend/src", "backend", "frontend/public"],
            cwd=str(v2_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff = result.stdout.strip()
        if not diff:
            # Try overall diff excluding node_modules
            result2 = subprocess.run(
                ["git", "diff"],
                cwd=str(v2_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff = result2.stdout.strip()
        return diff if diff else "(no code changes detected)"
    except Exception as e:
        return f"(git diff failed: {e})"


def get_changed_files(v2_dir: Path) -> List[str]:
    """Return list of modified source files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", "frontend/src", "backend"],
            cwd=str(v2_dir),
            capture_output=True,
            text=True,
            timeout=15,
        )
        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        if not files:
            result2 = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=str(v2_dir),
                capture_output=True,
                text=True,
                timeout=15,
            )
            files = [f.strip() for f in result2.stdout.strip().splitlines() if f.strip()
                     and "node_modules" not in f and not f.endswith(".log")]
        return files
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Telemetry summary
# ---------------------------------------------------------------------------

def load_telemetry_brief(v2_dir: Path) -> str:
    f = v2_dir / "telemetry_brief.md"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="ignore").strip()
    return "(not found)"


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _h(text: str) -> str:
    return html.escape(str(text))


def _verdict_badge(v: str) -> str:
    color = {"YES": "#22c55e", "NO": "#ef4444", "PARTIAL": "#f59e0b",
             "UNKNOWN": "#94a3b8", "N/A": "#e2e8f0"}.get(v, "#94a3b8")
    text_color = "white" if v not in ("N/A",) else "#475569"
    return f'<span style="background:{color};color:{text_color};padding:1px 6px;border-radius:3px;font-size:0.8em;font-weight:bold">{_h(v)}</span>'


def _collapsible(title: str, content_html: str, open_: bool = False) -> str:
    open_attr = " open" if open_ else ""
    return (
        f'<details{open_attr} style="margin:6px 0;border:1px solid #e2e8f0;border-radius:4px">'
        f'<summary style="cursor:pointer;padding:6px 10px;background:#f8fafc;font-weight:600">{title}</summary>'
        f'<div style="padding:10px">{content_html}</div></details>'
    )


def _diff_html(diff_text: str) -> str:
    lines = diff_text.splitlines()
    rows = []
    for line in lines:
        if line.startswith("+++") or line.startswith("---"):
            rows.append(f'<span style="color:#475569">{_h(line)}</span>')
        elif line.startswith("+"):
            rows.append(f'<span style="background:#dcfce7;color:#166534;display:block">{_h(line)}</span>')
        elif line.startswith("-"):
            rows.append(f'<span style="background:#fee2e2;color:#991b1b;display:block">{_h(line)}</span>')
        elif line.startswith("@@"):
            rows.append(f'<span style="color:#7c3aed;display:block">{_h(line)}</span>')
        else:
            rows.append(f'<span style="display:block">{_h(line)}</span>')
    return f'<pre style="font-size:0.82em;overflow-x:auto;background:#f8fafc;padding:8px;border-radius:4px">{"".join(rows)}</pre>'


# ---------------------------------------------------------------------------
# Core: build per-project HTML
# ---------------------------------------------------------------------------

def build_project_html(
    pid: str,
    run_dir: Path,
    v1_gate: int,
    v2_gate: int,
    gate_decision: str,
) -> str:
    """Build full HTML block for one project."""

    gen_dir = run_dir / f"gen_{pid}"
    v2_dir = gen_dir / f"project_{pid}_v2_experiment"
    v1_wv_dir = run_dir / "webvoyager_results" / pid
    v2_wv_dir = v2_dir / "webvoyager_v2_results"

    # ---- Load verdicts ----
    v1_verdicts = load_task_verdicts(v1_wv_dir)
    v2_verdicts = load_task_verdicts(v2_wv_dir)

    all_task_names = sorted(set(list(v1_verdicts.keys()) + list(v2_verdicts.keys())))

    # ---- Task comparison table ----
    table_rows = []
    improved_tasks = []
    regressed_tasks = []

    for t in all_task_names:
        v1v, v1txt = v1_verdicts.get(t, ("N/A", ""))
        v2v, v2txt = v2_verdicts.get(t, ("N/A", ""))
        short = _task_short_name(t)

        if v1v == "YES" and v2v != "YES":
            status = '<span style="color:#dc2626;font-weight:bold">⬇ Regressed</span>'
            regressed_tasks.append((t, v1v, v1txt, v2v, v2txt))
        elif v1v != "YES" and v2v == "YES":
            status = '<span style="color:#16a34a;font-weight:bold">⬆ Improved</span>'
            improved_tasks.append((t, v1v, v1txt, v2v, v2txt))
        elif v1v == v2v == "YES":
            status = '<span style="color:#64748b">✓ Both pass</span>'
        elif v1v == v2v:
            status = f'<span style="color:#64748b">= Same ({_h(v1v)})</span>'
        else:
            status = f'<span style="color:#f59e0b">{_h(v1v)}→{_h(v2v)}</span>'

        table_rows.append(
            f"<tr><td style='padding:3px 8px'>{_h(short)}</td>"
            f"<td style='padding:3px 8px'>{_verdict_badge(v1v)}</td>"
            f"<td style='padding:3px 8px'>{_verdict_badge(v2v)}</td>"
            f"<td style='padding:3px 8px'>{status}</td></tr>"
        )

    task_table_html = (
        '<table style="border-collapse:collapse;width:100%">'
        '<tr style="background:#f1f5f9"><th style="padding:4px 8px">Task</th>'
        '<th>v1</th><th>v2</th><th>变化</th></tr>'
        + "".join(table_rows)
        + "</table>"
    )

    # ---- Improved task details ----
    improved_html_parts = []
    for t, v1v, v1txt, v2v, v2txt in improved_tasks:
        v1_snippet = (v1txt[:800] + "...") if len(v1txt) > 800 else v1txt
        v2_snippet = (v2txt[:800] + "...") if len(v2txt) > 800 else v2txt
        improved_html_parts.append(
            f'<div style="margin:8px 0;padding:8px;background:#f0fdf4;border-left:3px solid #22c55e">'
            f'<strong>{_h(t)}</strong> ({_verdict_badge(v1v)} → {_verdict_badge(v2v)})<br>'
            f'<details><summary style="cursor:pointer;color:#666">v1 失败日志</summary>'
            f'<pre style="white-space:pre-wrap;font-size:0.8em;background:#fef2f2;padding:6px">{_h(v1_snippet)}</pre></details>'
            f'<details><summary style="cursor:pointer;color:#166534">v2 成功日志</summary>'
            f'<pre style="white-space:pre-wrap;font-size:0.8em;background:#dcfce7;padding:6px">{_h(v2_snippet)}</pre></details>'
            f'</div>'
        )

    # ---- Regressed task details ----
    regressed_html_parts = []
    for t, v1v, v1txt, v2v, v2txt in regressed_tasks:
        v1_snippet = (v1txt[:600] + "...") if len(v1txt) > 600 else v1txt
        v2_snippet = (v2txt[:600] + "...") if len(v2txt) > 600 else v2txt
        regressed_html_parts.append(
            f'<div style="margin:8px 0;padding:8px;background:#fef2f2;border-left:3px solid #ef4444">'
            f'<strong>{_h(t)}</strong> ({_verdict_badge(v1v)} → {_verdict_badge(v2v)})<br>'
            f'<details><summary style="cursor:pointer;color:#166534">v1 成功日志</summary>'
            f'<pre style="white-space:pre-wrap;font-size:0.8em;background:#dcfce7;padding:6px">{_h(v1_snippet)}</pre></details>'
            f'<details><summary style="cursor:pointer;color:#dc2626">v2 失败日志</summary>'
            f'<pre style="white-space:pre-wrap;font-size:0.8em;background:#fef2f2;padding:6px">{_h(v2_snippet)}</pre></details>'
            f'</div>'
        )

    # ---- OH summary ----
    oh_stdout = v2_dir / "openhands_repair_stdout.log"
    oh_summary = extract_oh_summary(oh_stdout)

    # ---- Git diff ----
    diff_text = get_git_diff(v2_dir)
    changed_files = get_changed_files(v2_dir)

    # ---- Telemetry ----
    telemetry = load_telemetry_brief(v2_dir)

    # ---- Compose project block ----
    v1_total = len([v for v, _ in v1_verdicts.values()])
    v2_total = len([v for v, _ in v2_verdicts.values()])
    delta = v2_gate - v1_gate
    delta_str = f"+{delta}" if delta > 0 else str(delta)

    if gate_decision == "keep":
        gate_badge = '<span style="background:#16a34a;color:white;padding:2px 8px;border-radius:3px">✓ 保留 v2</span>'
    elif gate_decision == "rollback":
        gate_badge = '<span style="background:#dc2626;color:white;padding:2px 8px;border-radius:3px">↩ 回退 v1</span>'
    else:
        gate_badge = '<span style="background:#94a3b8;color:white;padding:2px 8px;border-radius:3px">SKIP</span>'

    header_color = "#16a34a" if delta > 0 else ("#dc2626" if delta < 0 else "#475569")

    inner_html = f"""
    {_collapsible("逐任务对比", task_table_html, open_=True)}
    """

    if improved_tasks:
        inner_html += _collapsible(
            f"⬆ 改进任务详情 ({len(improved_tasks)} 个)",
            "".join(improved_html_parts),
            open_=True,
        )
    if regressed_tasks:
        inner_html += _collapsible(
            f"⬇ 退步任务详情 ({len(regressed_tasks)} 个)",
            "".join(regressed_html_parts),
            open_=False,
        )

    inner_html += _collapsible(
        f"OH 修改摘要 (修改文件: {', '.join(changed_files) if changed_files else '无'})",
        f'<pre style="white-space:pre-wrap;font-size:0.8em;overflow-x:auto">{_h(oh_summary)}</pre>',
        open_=bool(improved_tasks or regressed_tasks),
    )

    if changed_files:
        inner_html += _collapsible(
            f"代码变更 (git diff · {len(changed_files)} 文件修改)",
            _diff_html(diff_text),
            open_=False,
        )

    inner_html += _collapsible(
        "Telemetry Brief（v1 错误已知情况）",
        f'<pre style="white-space:pre-wrap;font-size:0.8em">{_h(telemetry[:3000])}</pre>',
        open_=False,
    )

    return f"""
<div id="proj-{pid}" style="margin:20px 0;border:2px solid {header_color};border-radius:8px;overflow:hidden">
  <div style="background:{header_color};color:white;padding:10px 16px;display:flex;align-items:center;gap:12px">
    <strong style="font-size:1.1em">#{pid}</strong>
    <span>v1: <strong>{v1_gate}/{v1_total}</strong></span>
    <span>→</span>
    <span>v2: <strong>{v2_gate}/{v2_total}</strong></span>
    <span style="font-size:1.2em;font-weight:bold">({delta_str})</span>
    {gate_badge}
  </div>
  <div style="padding:12px">
    {inner_html}
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Quality-gate log parser
# ---------------------------------------------------------------------------

def parse_quality_gate_log(log_path: Path) -> Dict[str, dict]:
    """Parse quality-gate log to extract v1/v2 counts and decision per project.

    Supports both formats:
      [quality-gate] v2=3 >= v1=2 — keeping v2 for 000031
      [quality-gate] v2=1 < v1=2 — rolling back 000037 to v1
    """
    results = {}
    if not log_path.exists():
        return results
    text = log_path.read_text(encoding="utf-8", errors="ignore")

    # Format 1: keeping v2 for <pid>
    keep_pat = re.compile(r"\[quality-gate\]\s+v2=(\d+)[^v]*v1=(\d+)[^\n]*?keeping[^\n]*?for\s+(\d+)")
    for m in keep_pat.finditer(text):
        v2, v1, pid = m.groups()
        results[pid.zfill(6)] = {"v1": int(v1), "v2": int(v2), "decision": "keep"}

    # Format 2: rolling back <pid> to v1
    rollback_pat = re.compile(r"\[quality-gate\]\s+v2=(\d+)[^v]*v1=(\d+)[^\n]*?rolling back\s+(\d+)")
    for m in rollback_pat.finditer(text):
        v2, v1, pid = m.groups()
        results[pid.zfill(6)] = {"v1": int(v1), "v2": int(v2), "decision": "rollback"}

    return results


def load_gate_from_summary(run_dir: Path) -> Dict[str, dict]:
    """Load quality gate results from dynamic_repair_batch_summary.json."""
    summary_file = run_dir / "dynamic_repair_batch_summary.json"
    results = {}
    if not summary_file.exists():
        return results
    try:
        data = json.loads(summary_file.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return results
    for proj in data.get("projects", []):
        pid = str(proj.get("project_id", "")).zfill(6)
        qg = proj.get("quality_gate") or {}
        v1_passes = qg.get("v1_passes")
        v2_passes = qg.get("v2_passes")
        decision = qg.get("decision")
        if v1_passes is not None and v2_passes is not None and decision:
            results[pid] = {"v1": v1_passes, "v2": v2_passes, "decision": decision}
    return results


def compute_gate_from_verdicts(pid: str, run_dir: Path) -> dict:
    """Compute v1/v2 pass counts directly from interact_messages when gate log is missing."""
    gen_dir = run_dir / f"gen_{pid}"
    v1_wv_dir = run_dir / "webvoyager_results" / pid
    v2_wv_dir = gen_dir / f"project_{pid}_v2_experiment" / "webvoyager_v2_results"

    v1v = load_task_verdicts(v1_wv_dir)
    v2v = load_task_verdicts(v2_wv_dir)

    # Only count YES (UNKNOWN/NO are not passes)
    v1_passes = sum(1 for v, _ in v1v.values() if v == "YES")
    v2_passes = sum(1 for v, _ in v2v.values() if v == "YES")
    decision = "keep" if v2_passes >= v1_passes else "rollback"
    return {"v1": v1_passes, "v2": v2_passes, "decision": decision}


def load_all_gate_results(run_dir: Path, projects: Optional[List[str]] = None) -> Dict[str, dict]:
    """Load quality gate results: log files → then summary JSON overrides → then computed fallback."""
    combined = {}

    # 1. From quality-gate log files (may include stale/old runs)
    import glob as _glob
    log_files: List[Path] = [run_dir / "quality_gate.log"]
    for f in _glob.glob("/tmp/optimize_run*.log") + _glob.glob("/tmp/optimize_rerun*.log"):
        log_files.append(Path(f))
    for log_path in log_files:
        combined.update(parse_quality_gate_log(log_path))

    # 2. Summary JSON overrides (most authoritative — written by the pipeline at the end)
    combined.update(load_gate_from_summary(run_dir))

    # 3. Compute from webvoyager results for any remaining missing projects
    if projects:
        for pid in projects:
            if pid not in combined:
                combined[pid] = compute_gate_from_verdicts(pid, run_dir)

    return combined


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_html_report(run_dir: Path, projects: Optional[List[str]], output_path: Path) -> None:
    # Discover projects if not specified
    if not projects:
        gen_dirs = sorted(p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("gen_"))
        projects = [d.name.split("gen_")[1] for d in gen_dirs]

    gate_results = load_all_gate_results(run_dir, projects)

    # Build overall stats
    total_v1 = total_v2_gate = total_final = 0
    project_rows_html = []

    # Summary table rows
    summary_rows = []

    for pid in projects:
        gate = gate_results.get(pid, {})
        v1_passes = gate.get("v1", 0)
        v2_passes = gate.get("v2", 0)
        decision = gate.get("decision", "unknown")
        final_passes = v1_passes if decision == "rollback" else v2_passes

        total_v1 += v1_passes
        total_v2_gate += v2_passes
        total_final += final_passes

        delta = final_passes - v1_passes
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        delta_color = "#16a34a" if delta > 0 else ("#dc2626" if delta < 0 else "#475569")

        proj_html = build_project_html(pid, run_dir, v1_passes, v2_passes, decision)
        project_rows_html.append(proj_html)

        gate_label = "✓ v2" if decision == "keep" else "↩ v1"
        summary_rows.append(
            f'<tr style="{"background:#f0fdf4" if delta>0 else ("background:#fef2f2" if delta<0 else "")}">'
            f'<td style="padding:4px 8px"><a href="#proj-{pid}">{pid}</a></td>'
            f'<td style="padding:4px 8px;text-align:center">{v1_passes}</td>'
            f'<td style="padding:4px 8px;text-align:center">{v2_passes}</td>'
            f'<td style="padding:4px 8px;text-align:center;color:{delta_color};font-weight:bold">{delta_str}</td>'
            f'<td style="padding:4px 8px;text-align:center">{gate_label}</td>'
            f'</tr>'
        )

    summary_table = (
        '<p style="font-size:0.85em;color:#64748b;margin:4px 0">'
        '⚠ 对于 dynamic_repair_batch_summary.json 未覆盖的项目（如 000001-000030），'
        'quality gate 决策由当前 webvoyager 结果自动推算，可能与历史 gate 运行略有差异。'
        '逐任务对比 (YES/NO) 始终来自实际 interact_messages。</p>'
        '<table style="border-collapse:collapse;width:100%;max-width:600px">'
        '<tr style="background:#f1f5f9"><th style="padding:4px 8px">PID</th>'
        '<th>v1</th><th>v2</th><th>delta</th><th>Gate</th></tr>'
        + "".join(summary_rows)
        + f'<tr style="background:#e2e8f0;font-weight:bold">'
        f'<td style="padding:4px 8px">合计</td>'
        f'<td style="padding:4px 8px;text-align:center">{total_v1}</td>'
        f'<td style="padding:4px 8px;text-align:center">→{total_final}</td>'
        f'<td style="padding:4px 8px;text-align:center;color:{"#16a34a" if total_final>total_v1 else "#dc2626"}">{total_final-total_v1:+d}</td>'
        f'<td></td></tr>'
        + "</table>"
    )

    html_report = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OH Repair Analysis — {run_dir.name}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 0; padding: 20px; background: #f8fafc; color: #1e293b; }}
  h1 {{ color: #1e293b; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
  h2 {{ color: #334155; margin-top: 32px; }}
  a {{ color: #3b82f6; }}
  details summary::-webkit-details-marker {{ display:none; }}
  details summary::before {{ content: "▶ "; font-size:0.8em; }}
  details[open] summary::before {{ content: "▼ "; }}
</style>
</head>
<body>
<h1>OH Repair Analysis</h1>
<p style="color:#64748b">Run: <code>{_h(str(run_dir))}</code></p>

<h2>总体结果</h2>
{summary_table}

<hr style="margin:32px 0">
<h2>逐项目详情</h2>
{"".join(project_rows_html)}
</body>
</html>
"""

    output_path.write_text(html_report, encoding="utf-8")
    print(f"Report written: {output_path}")
    print(f"Open in browser: open {output_path}")


def parse_project_range(spec: str) -> List[str]:
    """Parse '000001-000030,000031' style spec into list of zero-padded PIDs."""
    pids = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part and not part.startswith("-"):
            lo, hi = part.split("-", 1)
            try:
                for n in range(int(lo), int(hi) + 1):
                    pids.append(f"{n:06d}")
            except ValueError:
                pids.append(part)
        else:
            pids.append(part.zfill(6))
    return pids


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OH repair analysis HTML report")
    parser.add_argument("--run-dir", required=True, help="Path to batch run dir")
    parser.add_argument("--output", default="analysis_report.html", help="Output HTML path")
    parser.add_argument("--projects", default=None,
                        help="Comma/range list e.g. '000001-000030,000031'. Default: all found.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        print(f"ERROR: run-dir not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    projects = parse_project_range(args.projects) if args.projects else None
    output_path = Path(args.output).resolve()

    print(f"Building report for {run_dir.name}...")
    build_html_report(run_dir, projects, output_path)


if __name__ == "__main__":
    main()
