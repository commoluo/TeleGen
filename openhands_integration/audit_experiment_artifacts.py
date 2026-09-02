#!/usr/bin/env python3
"""Comprehensive audit of all experiment artifacts for TeleGen rebuttal."""

from __future__ import annotations
import csv, json, re, sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_DIR = REPO_ROOT / "batch_runs" / "official"
PAPER_MATERIALS = REPO_ROOT / "batch_runs" / "paper_materials"
OUTPUT_DIR = PAPER_MATERIALS / "output"

PRICING = {
    "deepseek-v4-flash": {"input": 0.27, "output": 1.10},
    "deepseek-v4-pro": {"input": 1.10, "output": 4.40},
    "qwen3.5-plus": {"input": 0.80, "output": 2.00},
}


@dataclass
class ProjectRecord:
    project_id: str = ""
    experiment: str = ""
    model: str = ""
    data_dir: str = ""
    v1_total_tokens: int = 0
    v1_prompt_tokens: int = 0
    v1_completion_tokens: int = 0
    v1_llm_call_count: int = 0
    v1_cost: float = 0.0
    v1_status: str = ""
    wv1_passed: int = 0
    wv1_total: int = 0
    wv1_status: str = ""
    brief_status: str = ""
    brief_model: str = ""
    brief_fast_path: str = ""
    brief_raw_entries: int = 0
    brief_retained_entries: int = 0
    brief_input_chars: int = 0
    logged_phase2_status: str = ""
    logged_total_tokens: int = 0
    logged_prompt_tokens: int = 0
    logged_completion_tokens: int = 0
    logged_llm_call_count: int = 0
    logged_cost: float = 0.0
    logged_conversation_id: str = ""
    logged_wv2_passed: int = 0
    logged_wv2_total: int = 0
    logged_wv2_status: str = ""
    logged_quality_gate: str = ""
    nolog_phase2_status: str = ""
    nolog_total_tokens: int = 0
    nolog_prompt_tokens: int = 0
    nolog_completion_tokens: int = 0
    nolog_llm_call_count: int = 0
    nolog_cost: float = 0.0
    nolog_conversation_id: str = ""
    nolog_wv2_passed: int = 0
    nolog_wv2_total: int = 0
    nolog_wv2_status: str = ""
    nolog_quality_gate: str = ""
    errors: List[str] = field(default_factory=list)


def si(val: Any) -> int:
    try: return int(val)
    except (TypeError, ValueError): return 0

def sf(val: Any) -> float:
    try: return float(val)
    except (TypeError, ValueError): return 0.0

def lj(path: Path) -> Optional[dict]:
    try: return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception: return None

def brief_stats(stdout: str) -> Dict[str, Any]:
    s: Dict[str, Any] = {}
    m = re.search(r"Loaded\s+(\d+)\s+raw entries.*retained\s+(\d+)\s+high-signal entries.*\((\d+)\s+chars", stdout)
    if m:
        s["raw_entries"] = int(m.group(1))
        s["retained_entries"] = int(m.group(2))
        s["input_chars"] = int(m.group(3))
    m2 = re.search(r"fast_path=(\w+)", stdout)
    if m2: s["fast_path"] = m2.group(1)
    return s

def est_cost(model: str, pt: int, ct: int) -> float:
    p = PRICING.get(model, PRICING["deepseek-v4-flash"])
    return (pt / 1e6) * p["input"] + (ct / 1e6) * p["output"]

def count_wv(wv_dir: Path) -> Tuple[int, int]:
    total = passed = 0
    if not wv_dir.exists(): return 0, 0
    for d in sorted(wv_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("task"): continue
        total += 1
        ef = d / "eval.json"
        if ef.exists():
            data = lj(ef)
            if data and data.get("score") in (1, "1", "success", True): passed += 1
    return passed, total


def scan_dual_repair(pdir: Path, exp: str, model: str) -> Optional[ProjectRecord]:
    sf_path = pdir / "baseline_dual_repair_summary.json"
    if not sf_path.exists(): return None
    data = lj(sf_path)
    if not data: return None
    r = ProjectRecord()
    r.project_id = str(data.get("project_id", pdir.name.replace("project_", "")))
    r.experiment = exp; r.model = model; r.data_dir = str(pdir)
    v1 = data.get("v1", {})
    if not isinstance(v1, dict): v1 = {}
    vb = v1.get("batch_result", {})
    if not isinstance(vb, dict): vb = {}
    r.v1_total_tokens = si(vb.get("openhands_total_tokens"))
    r.v1_prompt_tokens = si(vb.get("openhands_prompt_tokens"))
    r.v1_completion_tokens = si(vb.get("openhands_completion_tokens"))
    r.v1_llm_call_count = si(vb.get("openhands_max_iterations"))
    r.v1_cost = sf(vb.get("openhands_cost"))
    r.v1_status = str(vb.get("webvoyager_status", ""))
    wvd = Path(v1.get("webvoyager_results", ""))
    if wvd.exists(): r.wv1_passed, r.wv1_total = count_wv(wvd)
    repairs = data.get("repairs", {})
    if not isinstance(repairs, dict): repairs = {}
    lg = repairs.get("logged", {})
    if not isinstance(lg, dict): lg = {}
    p2l = lg.get("phase2", {})
    if not isinstance(p2l, dict): p2l = {}
    p3l = lg.get("phase3", {})
    if not isinstance(p3l, dict): p3l = {}
    r.logged_phase2_status = str(p2l.get("status", ""))
    r.logged_total_tokens = si(p2l.get("openhands_total_tokens"))
    r.logged_prompt_tokens = si(p2l.get("openhands_prompt_tokens"))
    r.logged_completion_tokens = si(p2l.get("openhands_completion_tokens"))
    r.logged_llm_call_count = si(p2l.get("openhands_llm_call_count"))
    r.logged_cost = sf(p2l.get("openhands_cost"))
    r.logged_conversation_id = str(p2l.get("openhands_conversation_id", ""))
    r.logged_wv2_passed = si(p3l.get("success_count"))
    r.logged_wv2_total = si(p3l.get("success_count", 0)) + si(p3l.get("failed_count", 0))
    r.logged_wv2_status = str(p3l.get("status", ""))
    r.logged_quality_gate = str(lg.get("quality_gate", {}).get("decision", ""))
    br = lg.get("phase1_brief", {})
    if not isinstance(br, dict): br = {}
    r.brief_status = str(br.get("status", ""))
    r.brief_model = str(br.get("selected_model", ""))
    bs = brief_stats(str(br.get("stdout", "")))
    r.brief_fast_path = str(bs.get("fast_path", ""))
    r.brief_raw_entries = int(bs.get("raw_entries", 0))
    r.brief_retained_entries = int(bs.get("retained_entries", 0))
    r.brief_input_chars = int(bs.get("input_chars", 0))
    nl = repairs.get("no_log", {})
    if not isinstance(nl, dict): nl = {}
    p2n = nl.get("phase2", {})
    if not isinstance(p2n, dict): p2n = {}
    p3n = nl.get("phase3", {})
    if not isinstance(p3n, dict): p3n = {}
    r.nolog_phase2_status = str(p2n.get("status", ""))
    r.nolog_total_tokens = si(p2n.get("openhands_total_tokens"))
    r.nolog_prompt_tokens = si(p2n.get("openhands_prompt_tokens"))
    r.nolog_completion_tokens = si(p2n.get("openhands_completion_tokens"))
    r.nolog_llm_call_count = si(p2n.get("openhands_llm_call_count"))
    r.nolog_cost = sf(p2n.get("openhands_cost"))
    r.nolog_conversation_id = str(p2n.get("openhands_conversation_id", ""))
    r.nolog_wv2_passed = si(p3n.get("success_count"))
    r.nolog_wv2_total = si(p3n.get("success_count", 0)) + si(p3n.get("failed_count", 0))
    r.nolog_wv2_status = str(p3n.get("status", ""))
    r.nolog_quality_gate = str(nl.get("quality_gate", {}).get("decision", ""))
    if r.v1_cost == 0 and r.v1_prompt_tokens > 0:
        r.v1_cost = est_cost(model, r.v1_prompt_tokens, r.v1_completion_tokens)
    if r.logged_cost == 0 and r.logged_prompt_tokens > 0:
        r.logged_cost = est_cost(model, r.logged_prompt_tokens, r.logged_completion_tokens)
    if r.nolog_cost == 0 and r.nolog_prompt_tokens > 0:
        r.nolog_cost = est_cost(model, r.nolog_prompt_tokens, r.nolog_completion_tokens)
    return r


def scan_single_repair(sf_path: Path, exp: str, model: str) -> Optional[ProjectRecord]:
    data = lj(sf_path)
    if not data: return None
    # Handle batch-level files with a "projects" array
    if "projects" in data and isinstance(data["projects"], list) and data["projects"]:
        projs = data["projects"]
        pdata = projs[0] if isinstance(projs[0], dict) else {}
    else:
        pdata = data
    r = ProjectRecord()
    r.project_id = str(pdata.get("project_id", ""))
    r.experiment = exp; r.model = model; r.data_dir = str(sf_path.parent)
    fname = sf_path.name
    cond = "logged" if "logged" in fname else "no_log" if "no_log" in fname else "unknown"
    br = pdata.get("phase1_brief", {})
    if not isinstance(br, dict): br = {}
    r.brief_status = str(br.get("status", ""))
    r.brief_model = str(br.get("selected_model", ""))
    bs = brief_stats(str(br.get("stdout", "")))
    r.brief_fast_path = str(bs.get("fast_path", ""))
    r.brief_raw_entries = int(bs.get("raw_entries", 0))
    r.brief_retained_entries = int(bs.get("retained_entries", 0))
    r.brief_input_chars = int(bs.get("input_chars", 0))
    p2 = pdata.get("phase2", {}); p3 = pdata.get("phase3", {})
    if not isinstance(p2, dict): p2 = {}
    if not isinstance(p3, dict): p3 = {}
    qg = pdata.get("quality_gate", {})
    if not isinstance(qg, dict): qg = {}
    if cond == "logged":
        r.logged_phase2_status = str(p2.get("status", ""))
        r.logged_total_tokens = si(p2.get("openhands_total_tokens"))
        r.logged_prompt_tokens = si(p2.get("openhands_prompt_tokens"))
        r.logged_completion_tokens = si(p2.get("openhands_completion_tokens"))
        r.logged_llm_call_count = si(p2.get("openhands_llm_call_count"))
        r.logged_cost = sf(p2.get("openhands_cost"))
        r.logged_conversation_id = str(p2.get("openhands_conversation_id", ""))
        r.logged_wv2_passed = si(p3.get("success_count"))
        r.logged_wv2_total = si(p3.get("success_count", 0)) + si(p3.get("failed_count", 0))
        r.logged_wv2_status = str(p3.get("status", ""))
        r.logged_quality_gate = str(qg.get("decision", ""))
    elif cond == "no_log":
        r.nolog_phase2_status = str(p2.get("status", ""))
        r.nolog_total_tokens = si(p2.get("openhands_total_tokens"))
        r.nolog_prompt_tokens = si(p2.get("openhands_prompt_tokens"))
        r.nolog_completion_tokens = si(p2.get("openhands_completion_tokens"))
        r.nolog_llm_call_count = si(p2.get("openhands_llm_call_count"))
        r.nolog_cost = sf(p2.get("openhands_cost"))
        r.nolog_conversation_id = str(p2.get("openhands_conversation_id", ""))
        r.nolog_wv2_passed = si(p3.get("success_count"))
        r.nolog_wv2_total = si(p3.get("success_count", 0)) + si(p3.get("failed_count", 0))
        r.nolog_wv2_status = str(p3.get("status", ""))
        r.nolog_quality_gate = str(qg.get("decision", ""))
    if r.logged_cost == 0 and r.logged_prompt_tokens > 0:
        r.logged_cost = est_cost(model, r.logged_prompt_tokens, r.logged_completion_tokens)
    if r.nolog_cost == 0 and r.nolog_prompt_tokens > 0:
        r.nolog_cost = est_cost(model, r.nolog_prompt_tokens, r.nolog_completion_tokens)
    return r


# ── Experiment configs ───────────────────────────────────────────────────────

EXPERIMENTS = {
    "flash_llm_full": {
        "model": "deepseek-v4-flash",
        "dirs": [
            "flash_llm_injection_data/multi_docker_full101_20260513_1242",
            "flash_llm_injection_data/multi_docker_run_20260513_022145",
            "flash_llm_injection_data/multi_docker_run_20260513_022145_retries",
            "flash_llm_injection_data/multi_docker_run_20260513_022645",
            "flash_llm_injection_data/multi_docker_run_20260513_023000",
            "flash_llm_injection_data/full101_watchdog_20260513_1242",
            "flash_llm_injection_data/full101_missing8_retry2_20260513_2055",
            "flash_llm_injection_data/full101_missing20_retry_20260513_1833",
            "flash_llm_injection_data/full101_missing3_retry3_20260513_2201",
            "flash_llm_injection_data/watchdog_retries_20260513_022145",
        ],
        "scanner": "dual",
    },
    "flash_raw_logs": {
        "model": "deepseek-v4-flash",
        "dirs": ["flash_raw_logs_ablation"],
        "scanner": "single",
    },
    "pro_llm_full": {
        "model": "deepseek-v4-pro",
        "dirs": ["pro_llm_injection"],
        "scanner": "dual",
    },
    "pro_raw_logs": {
        "model": "deepseek-v4-pro",
        "dirs": ["pro_raw_logs_ablation"],
        "scanner": "single",
    },
}


def scan_experiment(name: str, cfg: dict) -> List[ProjectRecord]:
    """Scan one experiment, deduplicating by project_id (first found wins)."""
    model = cfg["model"]
    scanner = cfg["scanner"]
    records: Dict[str, ProjectRecord] = {}
    for rel_dir in cfg["dirs"]:
        d = OFFICIAL_DIR / rel_dir
        if not d.exists():
            print(f"  [WARN] Missing: {d}")
            continue
        for pdir in sorted(d.iterdir()):
            if not pdir.is_dir() or not pdir.name.startswith("project_"):
                continue
            rec = None
            if scanner == "dual":
                rec = scan_dual_repair(pdir, name, model)
            else:
                for sfname in ["dynamic_repair_logged_summary.json",
                               "dynamic_repair_no_log_summary.json",
                               "dynamic_repair_batch_summary.json"]:
                    sf = pdir / sfname
                    if sf.exists():
                        rec = scan_single_repair(sf, name, model)
                        if rec: break
            if rec and rec.project_id and rec.project_id not in records:
                records[rec.project_id] = rec
    return list(records.values())


def aggregate_experiment(records: List[ProjectRecord]) -> dict:
    """Compute aggregate stats for one experiment."""
    n = len(records)
    if n == 0:
        return {"num_projects": 0}
    agg: Dict[str, Any] = {"num_projects": n}
    for field_name in ["v1_total_tokens", "v1_prompt_tokens", "v1_completion_tokens",
                       "logged_total_tokens", "logged_prompt_tokens", "logged_completion_tokens",
                       "nolog_total_tokens", "nolog_prompt_tokens", "nolog_completion_tokens",
                       "v1_cost", "logged_cost", "nolog_cost"]:
        vals = [getattr(r, field_name) for r in records]
        agg[f"total_{field_name}"] = sum(vals)
        agg[f"avg_{field_name}"] = sum(vals) / n
    # Pass counts
    agg["wv1_passed"] = sum(r.wv1_passed for r in records)
    agg["wv1_total"] = sum(r.wv1_total for r in records)
    agg["logged_wv2_passed"] = sum(r.logged_wv2_passed for r in records)
    agg["logged_wv2_total"] = sum(r.logged_wv2_total for r in records)
    agg["nolog_wv2_passed"] = sum(r.nolog_wv2_passed for r in records)
    agg["nolog_wv2_total"] = sum(r.nolog_wv2_total for r in records)
    # Telemetry stats
    raw_vals = [r.brief_raw_entries for r in records if r.brief_raw_entries > 0]
    ret_vals = [r.brief_retained_entries for r in records if r.brief_retained_entries > 0]
    if raw_vals:
        agg["brief_raw_entries_total"] = sum(raw_vals)
        agg["brief_raw_entries_avg"] = sum(raw_vals) / len(raw_vals)
    if ret_vals:
        agg["brief_retained_entries_total"] = sum(ret_vals)
        agg["brief_retained_entries_avg"] = sum(ret_vals) / len(ret_vals)
    if raw_vals and ret_vals:
        agg["brief_compression_ratio"] = sum(ret_vals) / sum(raw_vals)
    # Quality gates
    agg["logged_keep"] = sum(1 for r in records if r.logged_quality_gate == "keep")
    agg["logged_rollback"] = sum(1 for r in records if r.logged_quality_gate == "rollback")
    agg["nolog_keep"] = sum(1 for r in records if r.nolog_quality_gate == "keep")
    agg["nolog_rollback"] = sum(1 for r in records if r.nolog_quality_gate == "rollback")
    # Success rates
    if agg["wv1_total"] > 0:
        agg["v1_rate"] = round(100 * agg["wv1_passed"] / agg["wv1_total"], 2)
    if agg["logged_wv2_total"] > 0:
        agg["logged_rate"] = round(100 * agg["logged_wv2_passed"] / agg["logged_wv2_total"], 2)
    if agg["nolog_wv2_total"] > 0:
        agg["nolog_rate"] = round(100 * agg["nolog_wv2_passed"] / agg["nolog_wv2_total"], 2)
    return agg


# ── Report generators ────────────────────────────────────────────────────────

def write_inventory_json(all_records: Dict[str, List[ProjectRecord]], path: Path):
    out = {}
    for exp, recs in all_records.items():
        out[exp] = [asdict(r) for r in recs]
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def write_inventory_md(all_records: Dict[str, List[ProjectRecord]], path: Path):
    lines = ["# Artifact Inventory\n"]
    for exp, recs in sorted(all_records.items()):
        lines.append(f"## {exp} ({len(recs)} projects)\n")
        lines.append("| Project | V1 tokens | Logged tokens | NoLog tokens | V1 pass | Logged pass | NoLog pass | QG(log) | QG(nolog) |")
        lines.append("|---------|-----------|---------------|--------------|---------|-------------|------------|---------|-----------|")
        for r in sorted(recs, key=lambda x: x.project_id):
            lines.append(f"| {r.project_id} | {r.v1_total_tokens:,} | {r.logged_total_tokens:,} | {r.nolog_total_tokens:,} | {r.wv1_passed}/{r.wv1_total} | {r.logged_wv2_passed}/{r.logged_wv2_total} | {r.nolog_wv2_passed}/{r.nolog_wv2_total} | {r.logged_quality_gate} | {r.nolog_quality_gate} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_collectability_matrix(all_records: Dict[str, List[ProjectRecord]], path: Path):
    dimensions = [
        ("v1_token_usage", "v1_prompt_tokens"),
        ("v1_completion_tokens", "v1_completion_tokens"),
        ("logged_repair_tokens", "logged_prompt_tokens"),
        ("nolog_repair_tokens", "nolog_prompt_tokens"),
        ("telemetry_brief", "brief_status"),
        ("telemetry_volume", "brief_raw_entries"),
        ("logged_wv2_results", "logged_wv2_total"),
        ("nolog_wv2_results", "nolog_wv2_total"),
        ("quality_gate_logged", "logged_quality_gate"),
        ("quality_gate_nolog", "nolog_quality_gate"),
    ]
    rows = []
    for exp, recs in sorted(all_records.items()):
        row = {"experiment": exp, "num_projects": len(recs)}
        for dim_name, field_name in dimensions:
            collected = sum(1 for r in recs if getattr(r, field_name, 0) not in (0, "", None))
            row[dim_name] = f"{collected}/{len(recs)}"
        rows.append(row)
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not rows:
            return
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def write_cost_analysis(all_aggs: Dict[str, dict], path_json: Path, path_md: Path):
    path_json.write_text(json.dumps(all_aggs, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Cost Analysis\n"]
    lines.append("| Experiment | Model | Projects | V1 Tokens | Logged Tokens | NoLog Tokens | V1 Cost $ | Logged Cost $ | NoLog Cost $ | Total Cost $ |")
    lines.append("|------------|-------|----------|-----------|---------------|--------------|-----------|---------------|--------------|--------------|")
    for exp, a in sorted(all_aggs.items()):
        v1t = a.get("total_v1_total_tokens", 0)
        lgt = a.get("total_logged_total_tokens", 0)
        nlt = a.get("total_nolog_total_tokens", 0)
        v1c = a.get("total_v1_cost", 0)
        lgc = a.get("total_logged_cost", 0)
        nlc = a.get("total_nolog_cost", 0)
        lines.append(f"| {exp} | - | {a.get('num_projects',0)} | {v1t:,} | {lgt:,} | {nlt:,} | {v1c:.2f} | {lgc:.2f} | {nlc:.2f} | {v1c+lgc+nlc:.2f} |")
    lines.append("")
    path_md.write_text("\n".join(lines), encoding="utf-8")


def write_rebuttal_summary(all_aggs: Dict[str, dict], path: Path):
    lines = ["# Rebuttal Summary: Key Results\n"]
    lines.append("## RQ1: Category Effectiveness (DeepSeek-V4-Flash)\n")
    lines.append("| Stage | Passed | Total | Rate |")
    lines.append("|-------|--------|-------|------|")
    for exp in ["flash_llm_full"]:
        a = all_aggs.get(exp, {})
        if not a:
            continue
        lines.append(f"| V1 (initial gen) | {a.get('wv1_passed',0)} | {a.get('wv1_total',0)} | {a.get('v1_rate',0):.1f}% |")
        lines.append(f"| No-telemetry (baseline) | {a.get('nolog_wv2_passed',0)} | {a.get('nolog_wv2_total',0)} | {a.get('nolog_rate',0):.1f}% |")
        lines.append(f"| Observable repair (logged) | {a.get('logged_wv2_passed',0)} | {a.get('logged_wv2_total',0)} | {a.get('logged_rate',0):.1f}% |")
    lines.append("")
    lines.append("## RQ2: Token Efficiency\n")
    lines.append("| Experiment | V1 Avg Tokens | Logged Avg Tokens | NoLog Avg Tokens | Logged Overhead vs NoLog |")
    lines.append("|------------|---------------|-------------------|------------------|--------------------------|")
    for exp, a in sorted(all_aggs.items()):
        v1a = a.get("avg_v1_total_tokens", 0)
        lga = a.get("avg_logged_total_tokens", 0)
        nla = a.get("avg_nolog_total_tokens", 0)
        overhead = lga - nla if lga > 0 and nla > 0 else 0
        lines.append(f"| {exp} | {v1a:,.0f} | {lga:,.0f} | {nla:,.0f} | {overhead:,.0f} |")
    lines.append("")
    lines.append("## Telemetry Compression\n")
    lines.append("| Experiment | Raw Entries (total) | Retained Entries (total) | Compression Ratio |")
    lines.append("|------------|---------------------|--------------------------|-------------------|")
    for exp, a in sorted(all_aggs.items()):
        raw = a.get("brief_raw_entries_total", 0)
        ret = a.get("brief_retained_entries_total", 0)
        ratio = a.get("brief_compression_ratio", 0)
        lines.append(f"| {exp} | {raw} | {ret} | {ratio:.3f} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_stage_wise_summary(all_aggs: Dict[str, dict], path: Path):
    lines = ["# Stage-wise Summary\n"]
    lines.append("| Experiment | Stage | Avg Tokens | Total Tokens | Avg Cost $ | Total Cost $ |")
    lines.append("|------------|-------|------------|--------------|------------|--------------|")
    for exp, a in sorted(all_aggs.items()):
        n = a.get("num_projects", 1)
        for stage, prefix in [("V1 Generation", "v1"), ("Logged Repair", "logged"), ("No-Log Repair", "nolog")]:
            at = a.get(f"avg_{prefix}_total_tokens", 0)
            tt = a.get(f"total_{prefix}_total_tokens", 0)
            ac = a.get(f"avg_{prefix}_cost", 0)
            tc = a.get(f"total_{prefix}_cost", 0)
            lines.append(f"| {exp} | {stage} | {at:,.0f} | {tt:,} | {ac:.4f} | {tc:.2f} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_data_quality_report(all_records: Dict[str, List[ProjectRecord]], path: Path):
    lines = ["# Data Quality Report\n"]
    for exp, recs in sorted(all_records.items()):
        lines.append(f"## {exp}\n")
        n = len(recs)
        missing_v1 = sum(1 for r in recs if r.v1_total_tokens == 0)
        missing_logged = sum(1 for r in recs if r.logged_total_tokens == 0)
        missing_nolog = sum(1 for r in recs if r.nolog_total_tokens == 0)
        missing_brief = sum(1 for r in recs if r.brief_status not in ("success", ""))
        lines.append(f"- Total projects: {n}")
        lines.append(f"- Missing V1 token data: {missing_v1}")
        lines.append(f"- Missing logged repair token data: {missing_logged}")
        lines.append(f"- Missing no-log repair token data: {missing_nolog}")
        lines.append(f"- Brief extraction issues: {missing_brief}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_records: Dict[str, List[ProjectRecord]] = {}
    all_aggs: Dict[str, dict] = {}

    print("=== TeleGen Experiment Artifact Audit ===\n")
    for name, cfg in EXPERIMENTS.items():
        print(f"Scanning: {name}")
        recs = scan_experiment(name, cfg)
        all_records[name] = recs
        agg = aggregate_experiment(recs)
        all_aggs[name] = agg
        print(f"  Found {len(recs)} projects")
        print(f"  V1: {agg.get('wv1_passed',0)}/{agg.get('wv1_total',0)} = {agg.get('v1_rate',0):.1f}%")
        print(f"  Logged: {agg.get('logged_wv2_passed',0)}/{agg.get('logged_wv2_total',0)} = {agg.get('logged_rate',0):.1f}%")
        print(f"  NoLog: {agg.get('nolog_wv2_passed',0)}/{agg.get('nolog_wv2_total',0)} = {agg.get('nolog_rate',0):.1f}%")
        print()

    # Write all outputs
    write_inventory_json(all_records, OUTPUT_DIR / "artifact_inventory.json")
    write_inventory_md(all_records, OUTPUT_DIR / "artifact_inventory.md")
    write_collectability_matrix(all_records, OUTPUT_DIR / "collectability_matrix.csv")
    write_cost_analysis(all_aggs, OUTPUT_DIR / "cost_analysis.json", OUTPUT_DIR / "cost_analysis.md")
    write_rebuttal_summary(all_aggs, OUTPUT_DIR / "rebuttal_summary.md")
    write_stage_wise_summary(all_aggs, OUTPUT_DIR / "stage_wise_summary.md")
    write_data_quality_report(all_records, OUTPUT_DIR / "data_quality_report.md")

    print("\n=== Outputs written to", OUTPUT_DIR, "===")
    for f in sorted(OUTPUT_DIR.glob("artifact_*.*")):
        print(f"  {f.name}")
    for f in sorted(OUTPUT_DIR.glob("collectability_*")):
        print(f"  {f.name}")
    for f in sorted(OUTPUT_DIR.glob("cost_analysis.*")):
        print(f"  {f.name}")
    for f in sorted(OUTPUT_DIR.glob("rebuttal_summary.*")):
        print(f"  {f.name}")
    for f in sorted(OUTPUT_DIR.glob("stage_wise_*")):
        print(f"  {f.name}")
    for f in sorted(OUTPUT_DIR.glob("data_quality_*")):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
