#!/usr/bin/env python3
"""Cross-reference: for each flash project, join
  (1) suspect patch ops (from _suspects.json),
  (2) WV flip status (nolog_only = logs hurt), and
  (3) runtime JS errors in the logged WV console_logs.json (ground truth).

Output a per-project verdict table + a CONFIRMED list where a runtime JS error
maps to a patched file (injection caused the failure).
"""
from __future__ import annotations
import json, re, os
from pathlib import Path
from collections import defaultdict

WS = Path(__file__).resolve().parent.parent
MANIFEST = WS / "openhands_integration" / "v1_source_manifest_flash_logged.json"
COMP = WS / "batch_runs" / "paper_materials" / "output" / "v1_logged_vs_nolog_flash.json"
SUS = WS / "batch_runs" / "paper_materials" / "patches_review" / "_suspects.json"
OUT = WS / "batch_runs" / "paper_materials" / "patches_review" / "_crossref.json"

JS_ERR = re.compile(r"(ReferenceError|SyntaxError|TypeError|RangeError|is not defined|"
                     r"Uncaught|Unexpected token|Unexpected end|Cannot read prop|"
                     r"Rendered more hooks|is not a function|Maximum update)")
# errors that are clearly not injection-related
NOISE = re.compile(r"Failed to fetch|Failed to load resource|favicon|net::|404|502|503|ERR_")


def task_status(d: Path) -> str:
    ev = d / "webvoyager_auto_eval.json"
    if not ev.exists(): return "MISSING"
    try: return str(json.loads(ev.read_text()).get("status", "UNKNOWN"))
    except: return "EVAL_PARSE_ERROR"


def scan_project_console(logged_results_dir: Path):
    """Return list of (task_id, level, message) for JS-error-like entries."""
    hits = []
    if not logged_results_dir.exists(): return hits
    for tdir in sorted(p for p in logged_results_dir.iterdir() if p.is_dir() and p.name.startswith("task")):
        cl = tdir / "console_logs.json"
        if not cl.exists(): continue
        try:
            entries = json.loads(cl.read_text())
        except: continue
        for e in entries:
            msg = e.get("message", "")
            lvl = e.get("level", "")
            if not JS_ERR.search(msg): continue
            if NOISE.search(msg): continue
            hits.append({"task": tdir.name, "level": lvl, "msg": msg})
    return hits


def file_from_msg(msg: str):
    # message like: http://127.0.0.1:3000/src/components/Foo.jsx 24:14 "..."
    m = re.search(r"http[s]?://\S+?(/\S+?\.(?:jsx|tsx|js|ts))\b", msg)
    if m: return m.group(1)  # /src/components/Foo.jsx
    return None


def main():
    man = json.loads(MANIFEST.read_text())
    projects = man["projects"]
    comp = json.loads(COMP.read_text())
    sus = json.loads(SUS.read_text())

    # per-project flip counts
    flip_nolog_only = defaultdict(list)  # pid -> [task_id,...] logs hurt
    flip_logged_only = defaultdict(list)
    for f in comp["flipped_tasks"]:
        if f["direction"] == "nolog_only_success":
            flip_nolog_only[f["project_id"]].append(f["task_id"])
        elif f["direction"] == "logged_only_success":
            flip_logged_only[f["project_id"]].append(f["task_id"])

    # per-project suspect ops grouped
    by_proj = defaultdict(list)
    for s in sus["suspects"]:
        by_proj[s["project"]].append(s)

    rows = []
    confirmed = []
    for pid in sorted(projects):
        logged_dir = WS / projects[pid]["logged_results_dir"]
        errs = scan_project_console(logged_dir)
        sus_ops = by_proj.get(pid, [])
        # patched files in this project (relative path keys)
        patched_files = set(s["file"] for s in sus_ops)

        # map errors to suspect ops (category + identifier based, since bundled
        # chunk paths don't point at the original .jsx)
        err_on_patched = []
        for e in errs:
            f = file_from_msg(e["msg"])
            matched_ops = []
            msg = e["msg"]
            # 1) hooks-order violation -> hook_added ops
            if "Rendered more hooks" in msg or "hooks" in msg.lower():
                matched_ops = [s for s in sus_ops if "hook_added" in s["categories"]]
            # 2) ReferenceError: X is not defined -> ops whose added console.log refs X
            elif "is not defined" in msg or "ReferenceError" in msg:
                mvar = re.search(r"(?:ReferenceError:\s*|:\s*)([A-Za-z_$][\w$]*)\s+is not defined", msg)
                if mvar:
                    var = mvar.group(1)
                    matched_ops = [s for s in sus_ops
                                   if re.search(rf"\b{re.escape(var)}\b", "\n".join(s["detail"].get("added", [])))]
            # 3) source file path direct match
            if not matched_ops and f:
                matched_ops = [s for s in sus_ops
                               if s["file"].endswith(f.lstrip("/")) or f.lstrip("/") in s["file"]]
            err_on_patched.append({**e, "src_file": f, "matched_ops": matched_ops})

        n_logs_hurt = len(flip_nolog_only[pid])
        n_logs_help = len(flip_logged_only[pid])
        has_confirmed = any(x["matched_ops"] for x in err_on_patched)

        rows.append({
            "project": pid,
            "suspect_ops": len(sus_ops),
            "suspect_files": sorted(patched_files),
            "logs_hurt_tasks": flip_nolog_only[pid],
            "logs_help_tasks": flip_logged_only[pid],
            "n_logs_hurt": n_logs_hurt,
            "n_logs_help": n_logs_help,
            "runtime_js_errors": len(errs),
            "errors_on_patched_ops": [x for x in err_on_patched if x["matched_ops"]],
            "other_errors": [x for x in err_on_patched if not x["matched_ops"]],
            "confirmed": has_confirmed,
        })
        if has_confirmed:
            confirmed.append(rows[-1])

    OUT.write_text(json.dumps({"rows": rows, "confirmed": confirmed}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"projects={len(rows)}  with_logs_hurt={sum(1 for r in rows if r['n_logs_hurt'])}  "
          f"confirmed_runtime_err_on_patch={len(confirmed)}")
    print("\n=== CONFIRMED: runtime JS error mapped to a suspect patch op ===")
    for r in confirmed:
        print(f"  proj={r['project']}  logs_hurt={r['n_logs_hurt']}  logs_help={r['n_logs_help']}  "
              f"errs={r['runtime_js_errors']}")
        for e in r["errors_on_patched_ops"]:
            ops = e["matched_ops"]
            print(f"     [{e['task']}] ops={[ (o['file'],o['op'],o['categories']) for o in ops ]}")
            print(f"        msg: {e['msg'][:150]}")
    # also list projects with logs_hurt but no confirmed error (for manual triage)
    print("\n=== logs_hurt but NO confirmed runtime error (manual triage) ===")
    for r in rows:
        if r["n_logs_hurt"] > 0 and not r["confirmed"]:
            print(f"  proj={r['project']}  logs_hurt={r['n_logs_hurt']}  sus_ops={r['suspect_ops']}  "
                  f"runtime_errs={r['runtime_js_errors']}  other_errs={len(r['other_errors'])}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
