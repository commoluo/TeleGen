#!/usr/bin/env python3
"""Position-aligned detection of prop-value changes between clean and logged source.
For each file, diff clean vs logged; flag lines where `prop={X}` became `prop={Y}`
(same prop name, different value) at the same logical position. This avoids the
misalignment false positives of a naive regex scan.
"""
from __future__ import annotations
import json, re, difflib
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
man = json.loads((WS / "openhands_integration" / "v1_source_manifest_flash_logged.json").read_text())["projects"]
CROSS = json.loads((WS / "batch_runs" / "paper_materials" / "patches_review" / "_crossref.json").read_text())
flip_by_pid = {r["project"]: r["n_logs_hurt"] for r in CROSS["rows"]}

PROP_RE = re.compile(r'(\w+)=\{([A-Za-z_$][\w$]*)\}')


def prop_pairs(line: str):
    """Return dict prop->value for all prop={ident} occurrences in the line."""
    return {m.group(1): m.group(2) for m in PROP_RE.finditer(line)}


def main():
    changes = []
    for pid, info in man.items():
        llm = WS / info["clean_source"]
        clean = Path(str(llm).replace("_LLM", ""))
        if not llm.exists() or not clean.exists():
            continue
        for f in llm.rglob("*.jsx"):
            rel = f.relative_to(llm)
            cf = clean / rel
            if not cf.exists():
                continue
            try:
                a = cf.read_text(errors="ignore").splitlines()
                b = f.read_text(errors="ignore").splitlines()
            except Exception:
                continue
            sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != "replace":
                    continue
                # pair replaced lines one-to-one when counts match
                if (i2 - i1) == (j2 - j1) and (i2 - i1) == 1:
                    pa = prop_pairs(a[i1])
                    pb = prop_pairs(b[j1])
                    for prop, cv in pa.items():
                        lv = pb.get(prop)
                        if lv and cv != lv:
                            changes.append({
                                "project": pid, "file": str(rel),
                                "prop": prop, "clean_val": cv, "logged_val": lv,
                                "clean_line": a[i1].strip(), "logged_line": b[j1].strip(),
                                "logs_hurt": flip_by_pid.get(pid, 0),
                            })
    # classify
    setter_replaced = [c for c in changes if re.match(r"^set[A-Z]", c["clean_val"])]
    other = [c for c in changes if not re.match(r"^set[A-Z]", c["clean_val"])]

    out = WS / "batch_runs" / "paper_materials" / "patches_review" / "_prop_value_changes.json"
    out.write_text(json.dumps({"setter_replaced": setter_replaced, "other": other},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== setter replaced by wrapper (000002 pattern) — {len(setter_replaced)} ===")
    for c in setter_replaced:
        print(f"  🔥 proj={c['project']} {c['file']} prop={c['prop']}: "
              f"{c['clean_val']} -> {c['logged_val']}  (logs_hurt={c['logs_hurt']})")
    print(f"\n=== other prop value changes — {len(other)} (sample 25) ===")
    for c in other[:25]:
        print(f"  proj={c['project']} {c['file']} prop={c['prop']}: "
              f"{c['clean_val']} -> {c['logged_val']}  (logs_hurt={c['logs_hurt']})")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
