#!/usr/bin/env python3
"""Export log-injection patches, one file per project, in before/after (unified
diff) format, into a single review folder. Uses the canonical v1 `_LLM` dir per
project (from the logged manifest), so exactly 101 files (no retry/v2 dupes).
"""
from __future__ import annotations
import json, difflib
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
MANIFEST = WS / "openhands_integration" / "v1_source_manifest_flash_logged.json"
OUT = WS / "batch_runs" / "paper_materials" / "patches_review"
OUT.mkdir(parents=True, exist_ok=True)


def op_block(idx: int, reason: str, search: str, replace: str) -> str:
    s_lines = search.splitlines()
    r_lines = replace.splitlines()
    diff = difflib.unified_diff(s_lines, r_lines, lineterm="", n=2)
    diff_text = "\n".join(diff)
    parts = [f"### op {idx} — {reason or '(no reason)'}", ""]
    parts.append("```diff")
    if diff_text:
        parts.append(diff_text)
    else:
        parts.append("(无差异)")
    parts.append("```")
    parts.append("")
    parts.append("<details><summary>完整 search (原文)</summary>\n\n```js\n" + search.strip("\n") + "\n```\n</details>")
    parts.append("<details><summary>完整 replace (改后)</summary>\n\n```js\n" + replace.strip("\n") + "\n```\n</details>")
    parts.append("")
    return "\n".join(parts)


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    projects = manifest.get("projects") or {}
    n_written = 0
    summary = []
    for pid in sorted(projects):
        llm_dir = WS / projects[pid]["clean_source"]  # .../project_<id>_LLM
        patch_dir = llm_dir / ".llm_log_patches"
        md = [f"# Project {pid} — 日志注入 patch（前后对比）", "",
              f"源 (instrumented v1): `{llm_dir}`", ""]
        if not patch_dir.exists():
            md.append("⚠️ 无 `.llm_log_patches`（注入可能跳过/失败）。")
            (OUT / f"project_{pid}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
            summary.append((pid, 0, 0))
            continue
        patch_files = sorted(patch_dir.glob("*.json"))
        total_ops = 0
        for pf in patch_files:
            try:
                payload = json.loads(pf.read_text(encoding="utf-8"))
            except Exception as exc:
                md.append(f"## {pf.name} (解析失败: {exc})\n")
                continue
            rel = payload.get("file", pf.stem)
            ops = [o for o in payload.get("operations", []) if o.get("action") == "replace"]
            if not ops:
                continue
            md.append(f"## `{rel}`  ({len(ops)} ops)")
            md.append("")
            for i, op in enumerate(ops, 1):
                md.append(op_block(i, op.get("reason", ""), op.get("search", ""), op.get("replace", "")))
            total_ops += len(ops)
        md.insert(2, f"patch 文件: {len(patch_files)}，replace 操作: {total_ops}")
        (OUT / f"project_{pid}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        n_written += 1
        summary.append((pid, len(patch_files), total_ops))

    print(f"写出 {n_written} 个项目文件 -> {OUT}")
    print(f"总 patch 文件: {sum(s[1] for s in summary)}，总 replace 操作: {sum(s[2] for s in summary)}")
    no_patch = [p for p, pf, _ in summary if pf == 0]
    if no_patch:
        print(f"无 patch 的项目: {no_patch}")


if __name__ == "__main__":
    main()
