#!/usr/bin/env python3
"""Pre-screen log-injection patches and rank by structural change, so manual
review can focus on the operations most likely to contain a real logic change.

For each patch operation (search -> replace):
  - compute the line diff; lines that are console.log / [Telemetry] are ignored;
  - "substantive change score" = (# original lines removed/changed) + (# new
    non-console lines added), after best-effort undo of benign patterns
    (temp-variable extraction for logging, callback wrapping).
  - score 0  => console-only (auto benign)
  - score >0 => needs-review, exported SORTED by score desc (review top first).
"""
from __future__ import annotations
import json, glob, re, csv, difflib
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
OUT = WS / "batch_runs" / "paper_materials" / "output"
OUT.mkdir(parents=True, exist_ok=True)


def _is_console(line: str) -> bool:
    return "console.log" in line or "[Telemetry]" in line or "console.warn" in line or "console.error" in line


def undo_benign(replace: str) -> str:
    """Best-effort revert of logging-only rewrites so only real logic remains."""
    # 1) drop whole console.log(...) calls (balanced parens, multi-line)
    out = []
    i = 0
    while i < len(replace):
        m = re.compile(r"console\.(log|warn|error)\s*\(").search(replace, i)
        if not m:
            out.append(replace[i:]); break
        out.append(replace[i:m.start()])
        depth, j = 1, m.end()
        while j < len(replace) and depth > 0:
            if replace[j] == "(": depth += 1
            elif replace[j] == ")": depth -= 1
            j += 1
        if j < len(replace) and replace[j] == ";": j += 1  # swallow trailing ;
        i = j
    r = "".join(out)
    # 2) temp-variable extraction: `const v = EXPR;` then use v -> substitute EXPR, drop decl
    for m in list(re.finditer(r"\bconst\s+(\w+)\s*=\s*([^;]+);", r)):
        v, expr = m.group(1), m.group(2).strip()
        if not re.fullmatch(r"[A-Za-z0-9_\s.\-`/{}:$'\",?=+*()&|!<>]+", expr) or len(expr) > 100:
            continue
        body = r.replace(m.group(0), "", 1)
        if len(re.findall(r"\b" + re.escape(v) + r"\b", body)) >= 1:
            body = re.sub(r"\b" + re.escape(v) + r"\b", "(" + expr + ")", body)
            r = body
    # 3) callback wrap: (a) => { STMT; }  -> (a) => STMT
    r = re.sub(r"\(([^()]*?)\)\s*=>\s*\{\s*([^{};]+;)\s*\}", r"(\1) => \2", r)
    return r


def score_op(search: str, replace: str):
    """Return (score, sub_removed, sub_added)."""
    r2 = undo_benign(replace)
    s_lines = [l.rstrip() for l in search.splitlines() if l.strip()]
    r_lines = [l.rstrip() for l in r2.splitlines() if l.strip()]
    sm = difflib.SequenceMatcher(a=s_lines, b=r_lines, autojunk=False)
    removed, added = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            removed += s_lines[i1:i2]
        if tag in ("insert", "replace"):
            added += r_lines[j1:j2]
    sub_r = [l for l in removed if not _is_console(l)]
    sub_a = [l for l in added if not _is_console(l)]
    return len(sub_r) + len(sub_a), sub_r, sub_a


def main():
    all_rows = []
    review = []  # (score, project, file, op, reason, search, replace)
    n_console_only = 0
    for d in (glob.glob(str(WS / "batch_runs/official/flash_llm_injection_data/**/project_*_LLM/.llm_log_patches"), recursive=True)
              + glob.glob(str(WS / "batch_runs/official/pro_llm_injection/**/project_*_LLM/.llm_log_patches"), recursive=True)):
        proj = Path(d).parent.name.replace("project_", "").replace("_LLM", "")
        for pf in glob.glob(str(Path(d) / "*.json")):
            try:
                payload = json.loads(Path(pf).read_text(encoding="utf-8"))
            except Exception:
                continue
            rel = payload.get("file", Path(pf).stem)
            for i, op in enumerate(payload.get("operations", [])):
                if op.get("action") != "replace":
                    continue
                search = op.get("search", ""); replace = op.get("replace", "")
                sc, sr, sa = score_op(search, replace) if search and replace else (99, [], [])
                verdict = "console-only" if sc == 0 else "needs-review"
                if sc == 0:
                    n_console_only += 1
                else:
                    review.append((sc, proj, rel, i, op.get("reason", ""), search, replace, sr, sa))
                all_rows.append({"project": proj, "file": rel, "op": i, "score": sc, "verdict": verdict})

    review.sort(key=lambda x: -x[0])
    total = len(all_rows)
    with (OUT / "injection_patches_all.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["project", "file", "op", "score", "verdict"])
        w.writeheader(); w.writerows(all_rows)

    md = [f"# Log-injection patches — manual review (ranked by structural change)\n",
          f"Total operations: {total}. Auto-classified console-only (score 0): **{n_console_only}** "
          f"({n_console_only/total*100:.0f}%). Needs-review (score>0): **{len(review)}**.\n",
          "Score = # original code lines changed/removed + # new non-console lines added "
          "(after reverting logging-only temp-var extraction & callback wrapping). "
          "Higher score = more likely to contain a real logic change. Review top-down.\n",
          f"### Score distribution\n"]
    from collections import Counter
    dist = Counter(r[0] for r in review)
    for s in sorted(dist)[:15]:
        md.append(f"- score {s}: {dist[s]} ops")
    md.append("\n---\n")
    for n, (sc, proj, rel, opi, reason, search, replace, sr, sa) in enumerate(review[:250]):
        md.append(f"\n## [{n+1}] score={sc} · project {proj} · {rel} (op {opi})\n")
        md.append(f"reason: _{reason}_  | changed lines: removed {len(sr)}, added {len(sa)}\n")
        md.append("**search:**\n```\n" + search.strip() + "\n```\n**replace:**\n```\n" + replace.strip() + "\n```\n")
    if len(review) > 250:
        md.append(f"\n_...{len(review)-250} more lower-score ops in injection_patches_all.csv_\n")
    (OUT / "injection_patches_needs_review.md").write_text("\n".join(md), encoding="utf-8")

    print(f"operations: {total} | console-only(score0): {n_console_only} ({n_console_only/total*100:.0f}%) | needs-review: {len(review)}")
    print("score分布(top):", {s: dist[s] for s in sorted(dist)[:10]})
    print(f"outputs: injection_patches_all.csv, injection_patches_needs_review.md  (top 250 ranked)")


if __name__ == "__main__":
    main()
