#!/usr/bin/env python3
"""For every hook_added suspect, read the actual logged source and detect whether
the injected hook sits AFTER a conditional/early return in its component -> React
hooks-order violation (the 000083 pattern). Cross with flip + runtime error.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from collections import defaultdict

WS = Path(__file__).resolve().parent.parent

def _resolve(src_dir: str) -> Path:
    """Resolve a source_dir from _suspects.json; supports relative (new) and
    absolute (legacy) values, always anchored at WS when relative."""
    p = Path(src_dir)
    return p if p.is_absolute() else WS / p

SUS = WS / "batch_runs" / "paper_materials" / "patches_review" / "_suspects.json"
CROSS = WS / "batch_runs" / "paper_materials" / "patches_review" / "_crossref.json"

sus = json.loads(SUS.read_text())["suspects"]
cross = json.loads(CROSS.read_text())
flip_by_pid = {r["project"]: r["n_logs_hurt"] for r in cross["rows"]}
err_by_pid = {r["project"]: r["runtime_js_errors"] for r in cross["rows"]}

RETURN_RE = re.compile(r"^\s*return\b")
FUNC_START_RE = re.compile(r"^\s*(?:function\s+\w+|const\s+\w+\s*=\s*(?:\([^)]*\)\s*=>|[\w$]+\s*=>)|export\s+default\s+function|class\s+\w+)")


def find_hook_lines(src: str, added_lines: list[str], hook_calls: list[str]):
    """Locate the INJECTED hook by matching a unique telemetry line from the
    added block, then return (hook_call_text, line_of_the_hook_call)."""
    lines = src.splitlines()
    # prefer a unique console.log/telemetry line from the added block
    candidates = [l for l in added_lines if "console.log" in l or "[Telemetry]" in l]
    for cand in candidates:
        needle = cand.strip()
        if len(needle) < 12:
            continue
        for i, l in enumerate(lines, 1):
            if needle in l:
                # the hook call is a few lines above this telemetry line; find it
                for j in range(i, max(i - 6, 0), -1):
                    for hc in hook_calls:
                        if hc in lines[j - 1]:
                            return [(hc, j)]
                return [(hook_calls[0] if hook_calls else "", i)]
    # fallback: first occurrence of any new hook
    for hc in hook_calls:
        for i, l in enumerate(lines, 1):
            if hc in l:
                return [(hc, i)]
    return []


def early_return_before(lines: list[str], hook_line: int, func_start: int) -> int | None:
    """Scan backwards from hook_line to func_start; return line number of an early
    return if one exists (a return that is NOT the final return of the function).
    """
    # find the last 'return (' (final JSX return) at/after hook_line within reasonable range
    # an early return is any 'return ...;' before hook_line
    for i in range(hook_line - 1, func_start, -1):
        l = lines[i - 1]
        if RETURN_RE.match(l):
            return i
    return None


def find_func_start(lines: list[str], hook_line: int) -> int:
    """Scan backwards; return the OUTERMOST function/component start (the funcstart
    with the smallest indentation), so nested closures don't shadow it."""
    best = None  # (indent, line)
    for i in range(hook_line, 0, -1):
        l = lines[i - 1]
        if FUNC_START_RE.match(l):
            indent = len(l) - len(l.lstrip())
            if best is None or indent < best[0]:
                best = (indent, i)
            if indent == 0:
                break
    return best[1] if best else 1


def main():
    hook_suspects = [s for s in sus if "hook_added" in s["categories"]]
    dangerous = []
    print(f"hook_added suspects: {len(hook_suspects)}")
    for s in hook_suspects:
        src_path = _resolve(s["source_dir"]) / s["file"]
        if not src_path.exists():
            continue
        src = src_path.read_text(encoding="utf-8", errors="ignore")
        lines = src.splitlines()
        new_hooks = s["detail"].get("new_hooks", [])
        added_lines = s["detail"].get("added", [])
        if not new_hooks:
            continue
        found = find_hook_lines(src, added_lines, new_hooks)
        for hc, ln in found:
            fs = find_func_start(lines, ln)
            er = early_return_before(lines, ln, fs)
            if er:
                dangerous.append({
                    "project": s["project"], "file": s["file"], "op": s["op"],
                    "hook": hc, "hook_line": ln, "func_start": fs,
                    "early_return_line": er,
                    "early_return_text": lines[er - 1].strip(),
                    "logs_hurt": flip_by_pid.get(s["project"], 0),
                    "runtime_js_errors": err_by_pid.get(s["project"], 0),
                    "reason_hdr": s["reason_hdr"],
                    "source": str(src_path),
                })

    # sort: confirmed (logs_hurt>0 or runtime err) first
    dangerous.sort(key=lambda d: -(d["logs_hurt"] + d["runtime_js_errors"]))
    out = WS / "batch_runs" / "paper_materials" / "patches_review" / "_hook_after_return.json"
    out.write_text(json.dumps(dangerous, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== hook_added AFTER early return (hooks-order violation): {len(dangerous)} ===")
    for d in dangerous:
        flag = "🔥" if (d["logs_hurt"] or d["runtime_js_errors"]) else "  "
        print(f"{flag} proj={d['project']} {d['file']} op{d['op']} hook@L{d['hook_line']} "
              f"early_return@L{d['early_return_line']}: {d['early_return_text'][:55]}  "
              f"logs_hurt={d['logs_hurt']} rt_err={d['runtime_js_errors']}")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
