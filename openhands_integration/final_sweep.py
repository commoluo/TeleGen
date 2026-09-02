#!/usr/bin/env python3
"""Final sweep for two more behavior-changing patterns in logs_hurt projects:
  (a) injected console.log referencing an identifier that appears NOWHERE else in
      the file -> likely undefined variable (the user's example).
  (b) control_flow ops that ADD a new return/break/continue (real flow change,
      not else-log glue).
"""
from __future__ import annotations
import json, re
from pathlib import Path

WS = Path(__file__).resolve().parent.parent

def _resolve(src_dir: str) -> Path:
    """Resolve a source_dir from _suspects.json; supports relative (new) and
    absolute (legacy) values, always anchored at WS when relative."""
    p = Path(src_dir)
    return p if p.is_absolute() else WS / p

SUS = json.loads((WS / "batch_runs" / "paper_materials" / "patches_review" / "_suspects.json").read_text())["suspects"]
CROSS = json.loads((WS / "batch_runs" / "paper_materials" / "patches_review" / "_crossref.json").read_text())
hurt_pids = {r["project"] for r in CROSS["rows"] if r["n_logs_hurt"] > 0}

IDENT = re.compile(r"[A-Za-z_$][\w$]*")
# identifier NOT preceded by '.' (member access) and NOT followed by ':' (object key)
IDENT_BARE = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)(?!\s*:)")
STR_LIT = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
LOG_CALL = re.compile(r"console\.log\s*\(([\s\S]*?)\)\s*;?\s*$")
DECL_KW = re.compile(r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)")
PARAM_HOOK = re.compile(r"(?:function\s+\w+|=>)\s*\(([^)]*)\)|\(([^)]*)\)\s*=>")
GLOBALS = {"console","window","document","localStorage","sessionStorage","JSON","Math","Date",
           "Array","Object","String","Number","Boolean","Promise","Set","Map","fetch","setTimeout",
           "setInterval","clearTimeout","clearInterval","isNaN","parseFloat","parseInt","alert",
           "React","undefined","null","true","false","NaN","Infinity","Error","URL","FormData",
           "WebSocket","navigator","location","history","btoa","atob","encodeURIComponent",
           "decodeURIComponent","process","import","module","require","this","event","globalThis"}
# common props/refs that appear via destructuring/props - we check file-wide presence instead


def added_log_lines(s):
    out = []
    for l in s["detail"].get("added", []):
        if "console.log" in l:
            out.append(l)
    return out


def main():
    undef_hits = []
    flow_hits = []
    for s in SUS:
        if s["project"] not in hurt_pids:
            continue
        src_path = _resolve(s["source_dir"]) / s["file"]
        if not src_path.exists():
            continue
        src = src_path.read_text(errors="ignore")

        # (a) undefined-var in injected console.log
        for line in added_log_lines(s):
            # extract args inside console.log(...)
            m = re.search(r"console\.log\s*\(([\s\S]*)\)", line)
            if not m:
                continue
            args = m.group(1)
            # remove string/template literals
            args_nos = STR_LIT.sub(" ", args)
            for mobj in IDENT.finditer(args_nos):
                ident = mobj.group(0)
                start = mobj.start()
                # skip member access: preceded by '.'
                if start > 0 and args_nos[start - 1] == ".":
                    continue
                # skip object-literal key: followed by optional ws then ':'
                rest = args_nos[mobj.end():].lstrip()
                if rest.startswith(":"):
                    continue
                if ident in GLOBALS or ident.isdigit():
                    continue
                # does this identifier appear anywhere else in the file (outside this log line)?
                # count occurrences in whole file
                occurrences = len(re.findall(rf"\b{re.escape(ident)}\b", src))
                if occurrences <= 1:
                    undef_hits.append({
                        "project": s["project"], "file": s["file"], "op": s["op"],
                        "ident": ident, "log_line": line.strip(),
                        "occurrences_in_file": occurrences,
                    })

        # (b) real control-flow add: new return/break/continue in added lines
        for l in s["detail"].get("added", []):
            ls = l.strip()
            if re.match(r"^(return|break|continue)\b", ls) and "console.log" not in ls:
                # exclude `return res.json()` style that's part of safe then-restructure
                flow_hits.append({
                    "project": s["project"], "file": s["file"], "op": s["op"],
                    "line": ls, "reason": s["reason_hdr"],
                })

    # dedup undef by (project, ident)
    seen = set(); undef_dedup = []
    for h in undef_hits:
        k = (h["project"], h["ident"], h["file"])
        if k in seen: continue
        seen.add(k); undef_dedup.append(h)

    print(f"=== (a) injected console.log referencing identifier absent from file: {len(undef_dedup)} ===")
    for h in undef_dedup[:40]:
        print(f"  proj={h['project']} {h['file']} op{h['op']} ident=`{h['ident']}` (occurrences={h['occurrences_in_file']})")
        print(f"     log: {h['log_line'][:110]}")
    print(f"\n=== (b) added return/break/continue (real flow change): {len(flow_hits)} ===")
    for h in flow_hits[:40]:
        print(f"  proj={h['project']} {h['file']} op{h['op']}  `{h['line'][:60]}`  | {h['reason'][:45]}")

    out = WS / "batch_runs" / "paper_materials" / "patches_review" / "_final_sweep.json"
    out.write_text(json.dumps({"undef": undef_dedup, "flow": flow_hits}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
