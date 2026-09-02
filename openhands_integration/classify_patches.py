#!/usr/bin/env python3
"""Scan patches_review/*.md, classify each replace op as safe (pure log add) vs
suspect (behavior-changing). Output ranked suspects with source-file paths.

Suspect categories:
  - hook_added        : new useXxx() call (React hooks-order risk)
  - import_changed    : import line added/modified
  - logic_removed     : original line deleted / replaced (not just refactored to log)
  - new_binding       : new const/let/var/function declaration beyond pure logging
  - control_flow      : new/changed if|else|return|for|while|switch beyond log glue
  - prop_ref_changed  : a prop/identifier passed to JSX changed (e.g. setPage->wrapper)
  - async_restructure : fetch/await/.then chain restructured
  - syntax_risk       : braces unbalanced or template literal opened in added line
"""
from __future__ import annotations
import re, json, difflib
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
REV = WS / "batch_runs" / "paper_materials" / "patches_review"

FILE_HDR = re.compile(r"^## `(.+?)`\s+\((\d+) ops\)")
OP_HDR = re.compile(r"^### op (\d+)\s*[-—–]\s*(.*)")
SRC_HDR = re.compile(r"^源 \(instrumented v1\): `(.+)`")
DETAILS_SEARCH = "完整 search (原文)"
DETAILS_REPLACE = "完整 replace (改后)"

HOOK_RE = re.compile(r"\buse[A-Z]\w*\s*\(")
LOG_LINE_RE = re.compile(r"console\.log\s*\(")
TELEMETRY_RE = re.compile(r"\[Telemetry\]")
IMPORT_RE = re.compile(r"^\s*import\s|^import\s|^\s*import\b")
DECL_RE = re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")
FUNC_RE = re.compile(r"^\s*(?:async\s+)?function\s+|^\s*(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\(?\s*[\w$, ]*\s*\)?\s*=>")
CF_RE = re.compile(r"^\s*(?:if|else|for|while|switch|case|break|continue|return)\b")
AWAIT_FETCH_RE = re.compile(r"\bawait\b|\bfetch\s*\(|\.then\s*\(|\.catch\s*\(")


def parse_md(path: Path):
    """Return (source_dir, [(file, op_num, reason, search, replace), ...])."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    source_dir = None
    ops = []
    cur_file = None
    cur_op = None
    cur_reason = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = SRC_HDR.match(line)
        if m:
            source_dir = m.group(1)
            i += 1; continue
        m = FILE_HDR.match(line)
        if m:
            cur_file = m.group(1)
            i += 1; continue
        m = OP_HDR.match(line)
        if m:
            cur_op = int(m.group(1)); cur_reason = m.group(2).strip()
            i += 1; continue
        # find a <details> block; capture the ```js ... ``` inside
        if line.startswith("<details><summary>"):
            summary = line.removeprefix("<details><summary>").removesuffix("</summary>").strip()
            # next non-empty line should be ```js
            j = i + 1
            while j < n and lines[j].strip() == "":
                j += 1
            if j < n and lines[j].strip().startswith("```"):
                j += 1
                start = j
                while j < n and not lines[j].strip().startswith("```"):
                    j += 1
                content = "\n".join(lines[start:j])
                if summary == DETAILS_SEARCH:
                    search = content
                elif summary == DETAILS_REPLACE:
                    replace = content
                    if cur_file and cur_op is not None:
                        ops.append((cur_file, cur_op, cur_reason or "", search, replace))
                    cur_op = None
                i = j + 1; continue
        i += 1
    return source_dir, ops


def strip_comments_blank(line: str) -> str:
    s = line.strip()
    return s


def is_log_or_glue(line: str) -> bool:
    """A line that is purely logging or structural glue for a log insertion."""
    s = line.strip()
    if not s:
        return True
    if LOG_LINE_RE.search(s) or TELEMETRY_RE.search(s):
        return True
    # glue: pure braces / else / try-catch wrappers that typically accompany logs
    if s in ("{", "}", "};", ")") or s == "} else {" or s == "} else{" :
        return True
    if s.startswith("//"):
        return True
    return False


def classify(search: str, replace: str):
    s_lines = [l for l in search.splitlines()]
    r_lines = [l for l in replace.splitlines()]
    sm = difflib.SequenceMatcher(a=s_lines, b=r_lines, autojunk=False)
    added, removed, changed_pairs = [], [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            for l in r_lines[j1:j2]:
                added.append(l)
        elif tag == "delete":
            for l in s_lines[i1:i2]:
                removed.append(l)
        elif tag == "replace":
            # pair them up loosely
            for l in s_lines[i1:i2]:
                removed.append(l)
            for l in r_lines[j1:j2]:
                added.append(l)

    reasons = []
    detail = {"added": added, "removed": removed}

    # 1. hook added (not present in search)
    s_hooks = set(HOOK_RE.findall(search))
    r_hooks = set(HOOK_RE.findall(replace))
    new_hooks = r_hooks - s_hooks
    if new_hooks:
        reasons.append("hook_added")
        detail["new_hooks"] = sorted(new_hooks)

    # 2. import changed
    s_imports = [l for l in s_lines if IMPORT_RE.match(l)]
    r_imports = [l for l in r_lines if IMPORT_RE.match(l)]
    if r_imports != s_imports:
        reasons.append("import_changed")
        detail["import_diff"] = {"search": s_imports, "replace": r_imports}

    # 3. removed original lines (logic deleted / replaced)
    real_removed = [l for l in removed if l.strip() and not is_log_or_glue(l)]
    if real_removed:
        reasons.append("logic_removed")
        detail["real_removed"] = real_removed

    # 4. added non-log lines
    added_nonlog = [l for l in added if not is_log_or_glue(l)]
    if added_nonlog:
        # sub-classify
        new_bindings = [l for l in added_nonlog if DECL_RE.match(l) or FUNC_RE.match(l)]
        cf = [l for l in added_nonlog if CF_RE.match(l)]
        if new_bindings:
            reasons.append("new_binding")
            detail["new_bindings"] = new_bindings
        if cf:
            reasons.append("control_flow")
            detail["control_flow"] = cf
        # if there are added non-log lines not captured by binding/cf, still flag
        leftover = [l for l in added_nonlog if not (DECL_RE.match(l) or FUNC_RE.match(l) or CF_RE.match(l))]
        if leftover:
            reasons.append("other_added_logic")
            detail["other_added"] = leftover[:6]

    # 5. async/fetch restructure (await/fetch/then/catch appears in changed region)
    changed_blob = "\n".join(added + removed)
    if AWAIT_FETCH_RE.search(changed_blob) and (real_removed or added_nonlog):
        reasons.append("async_restructure")

    # 6. prop reference changed: identifier inside JSX prop changed
    #    detect: a line present in both but with a different identifier token
    #    cheap heuristic: search has `={setSomething}` / `={fn}` and replace changes it
    prop_changes = []
    for sl in s_lines:
        sls = sl.strip()
        m = re.search(r"=\{([A-Za-z_$][\w$]*)\}", sls)
        if not m:
            continue
        ident = m.group(1)
        # find closest replace line
        for rl in r_lines:
            rls = rl.strip()
            mr = re.search(r"=\{([A-Za-z_$][\w$]*)\}", rls)
            if mr and mr.group(1) != ident and difflib.SequenceMatcher(None, sls, rls).ratio() > 0.6:
                prop_changes.append((ident, mr.group(1), sls, rls))
                break
    if prop_changes:
        reasons.append("prop_ref_changed")
        detail["prop_changes"] = prop_changes

    # 7. syntax risk: unbalanced braces in replace vs search
    def bal(t):
        return t.count("{") - t.count("}"), t.count("(") - t.count(")")
    sb_b, sb_p = bal(search); rb_b, rb_p = bal(replace)
    if sb_b != rb_b or sb_p != rb_p:
        reasons.append("syntax_risk")
        detail["brace_delta"] = {"b": rb_b - sb_b, "p": rb_p - sb_p}

    safe = len(reasons) == 0
    return safe, reasons, detail


def main():
    files = sorted(REV.glob("project_*.md"))
    all_suspects = []
    totals = {"files": 0, "ops": 0, "safe": 0, "suspect": 0}
    by_cat = {}
    for f in files:
        pid = f.stem.split("_")[1]
        source_dir, ops = parse_md(f)
        if not ops:
            continue
        totals["files"] += 1
        for (rel, op_num, reason, search, replace) in ops:
            totals["ops"] += 1
            safe, reasons, detail = classify(search, replace)
            if safe:
                totals["safe"] += 1
                continue
            totals["suspect"] += 1
            for r in reasons:
                by_cat[r] = by_cat.get(r, 0) + 1
            all_suspects.append({
                "project": pid,
                "file": rel,
                "op": op_num,
                "reason_hdr": reason,
                "categories": reasons,
                "source_dir": source_dir,
                "detail": detail,
            })

    # rank: hook_added / prop_ref_changed / logic_removed first
    rank = {"hook_added": 0, "prop_ref_changed": 1, "logic_removed": 2,
            "control_flow": 3, "new_binding": 4, "async_restructure": 5,
            "import_changed": 6, "syntax_risk": 7, "other_added_logic": 8}
    def rank_key(s):
        return min((rank.get(c, 9) for c in s["categories"]), default=9)
    all_suspects.sort(key=rank_key)

    out = WS / "batch_runs" / "paper_materials" / "patches_review" / "_suspects.json"
    out.write_text(json.dumps({
        "totals": totals, "by_category": by_cat,
        "suspects": all_suspects,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"files={totals['files']} ops={totals['ops']} safe={totals['safe']} suspect={totals['suspect']}")
    print("by_category:", by_cat)
    print(f"\nTop suspects (first 40 of {len(all_suspects)}):")
    for s in all_suspects[:40]:
        print(f"  proj={s['project']} {s['file']} op{s['op']} {s['categories']} | {s['reason_hdr'][:70]}")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
