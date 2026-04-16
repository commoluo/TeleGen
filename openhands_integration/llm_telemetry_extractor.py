#!/usr/bin/env python3
"""LLM-based frontend console log extractor using a fixed analysis prompt."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from dotenv import load_dotenv


PROMPT_TEMPLATE = """You are a log analysis assistant. I will provide you with a frontend application console log.
Your job is to clean the noise, extract meaningful signals, and reconstruct a clear user
operation timeline.

Do NOT provide any fix suggestions, root cause analysis, or optimization advice.
Only describe what happened, factually and objectively.

## Discard the following (do not include in output)
- Any log containing [TRACE] (component render noise)
- Any log originating from node_modules, @vite/client, or third-party chunks
- Exact duplicate log entries (keep only the first occurrence)
- React DevTools tips or framework internal messages

## Retain and categorize the following
- [Telemetry] Interaction — user interaction events
- [Telemetry] Network Request / Network Response — API calls and results
- SEVERE level logs — all errors, preserved in full with file and line number

## Output Format

### Task Context
Describe in one sentence what the user was attempting to do, inferred strictly
from the interaction timeline. No speculation beyond what the logs show.

### User Operation Timeline
Reconstruct a chronological sequence of what happened. Each entry must follow
this format strictly:

[HH:MM:SS] <event_type> | <description> | <source_file>:<line>

Event types:
- USER_ACTION     -> user triggered an interaction (click, input, submit, etc.)
- API_REQUEST     -> a network request was made
- API_RESPONSE    -> a network response was received (include status code)
- ERROR           -> a SEVERE level error occurred
- STATE_CHANGE    -> an observable application state transition

Rules:
- If an event has no associated source file, write source as "unknown"
- If an API_REQUEST has no following API_RESPONSE, append "(no response recorded)"
- If multiple identical errors occurred, write the first one and append
  "(repeated N times)" instead of listing each one

### Error Summary
List each unique SEVERE error with the following fields:
- Location: <file>:<line>
- Message: <exact error message>
- Triggered after: <the USER_ACTION or API_RESPONSE that immediately preceded it>
- Call stack (condensed): <component chain, e.g. StockCard -> StockList -> App>
- Occurrences: <count>

### Affected Code Locations
List all source files and line numbers referenced across the timeline and error
summary. This will be used to retrieve relevant source code for the next stage.

Format:
- <file_path>:<line> - <one-phrase description of what happens there>

### Compression Report
- Raw log entries: <n>
- Retained entries: <n>
- Discarded breakdown:
  - Duplicate entries: <n>
  - [TRACE] render noise: <n>
  - Third-party / framework logs: <n>
  - Other: <n>

## Constraints
- Use only information present in the logs. Do not infer, speculate, or suggest.
- Keep all descriptions factual and concise.
- Do not include any section titled "Analysis", "Root Cause", or "Recommendations".
- The output will be passed directly to a code optimization model alongside
  the source code, so precision of file references is critical.

## Log input:
{paste logs here}
"""


def _load_env(workspace_root: Path) -> None:
    load_dotenv(workspace_root / ".env")
    load_dotenv(workspace_root / "alternative_generation" / ".env")


def _infer_provider_from_model(model: str) -> str:
    m = (model or "").lower()
    if "minimax" in m:
        return "minimax"
    if "qwen" in m:
        return "qwen"
    if "deepseek" in m:
        return "deepseek"
    return "generic"


def _resolve_api_base_url(model: str) -> str:
    provider = _infer_provider_from_model(model)
    if provider == "minimax":
        return os.getenv("WEBVOYAGER_BASE_URL") or os.getenv("MINIMAX_BASE_URL") or "https://api.minimaxi.com/v1"
    if provider == "qwen":
        return os.getenv("QWEN_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")
    # Prefer MiniMax endpoint when its credentials are present.
    if os.getenv("WEBVOYAGER_API_KEY") or os.getenv("MINIMAX_API_KEY"):
        return os.getenv("WEBVOYAGER_BASE_URL") or os.getenv("MINIMAX_BASE_URL") or "https://api.minimaxi.com/v1"
    return os.getenv("API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def _resolve_api_key(model: str, base_url: str) -> str:
    explicit = os.getenv("API_KEY")
    if explicit:
        return explicit

    provider = _infer_provider_from_model(model)
    url = (base_url or "").lower()
    if provider == "generic":
        if "deepseek.com" in url:
            provider = "deepseek"
        elif "minimaxi.com" in url:
            provider = "minimax"
        elif "dashscope.aliyuncs.com" in url:
            provider = "qwen"

    if provider == "minimax":
        return os.getenv("MINIMAX_API_KEY") or os.getenv("WEBVOYAGER_API_KEY") or ""

    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

    if provider == "qwen":
        return (
            os.getenv("QWEN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )

    return (
        os.getenv("QWEN_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def _api_key_candidates(model: str, base_url: str) -> List[Tuple[str, str]]:
    """Return ordered key candidates: [(source_name, api_key), ...]."""
    provider = _infer_provider_from_model(model)
    url = (base_url or "").lower()
    if provider == "generic":
        if "deepseek.com" in url:
            provider = "deepseek"
        elif "minimaxi.com" in url:
            provider = "minimax"
        elif "dashscope.aliyuncs.com" in url:
            provider = "qwen"

    candidates: List[Tuple[str, str]] = []
    if provider == "minimax":
        for name in ["MINIMAX_API_KEY", "WEBVOYAGER_API_KEY", "OPENAI_API_KEY"]:
            val = os.getenv(name)
            if val:
                candidates.append((name, val))
    elif provider == "qwen":
        for name in ["QWEN_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"]:
            val = os.getenv(name)
            if val:
                candidates.append((name, val))
    elif provider == "deepseek":
        for name in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
            val = os.getenv(name)
            if val:
                candidates.append((name, val))
    else:
        for name in ["API_KEY", "MINIMAX_API_KEY", "WEBVOYAGER_API_KEY", "QWEN_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
            val = os.getenv(name)
            if val:
                candidates.append((name, val))

    # Deduplicate by key value while preserving first source name.
    dedup: List[Tuple[str, str]] = []
    seen = set()
    for src, key in candidates:
        if key in seen:
            continue
        seen.add(key)
        dedup.append((src, key))

    return dedup


def _find_overlap_size(previous: str, current: str, max_window: int = 2000) -> int:
    if not previous or not current:
        return 0
    window = min(len(previous), len(current), max_window)
    for size in range(window, 0, -1):
        if previous[-size:] == current[:size]:
            return size
    return 0


def _chat_completion_once(model: str, messages: List[Dict[str, str]], max_tokens: int, timeout: int = 180) -> Tuple[str, str]:
    base_url = _resolve_api_base_url(model)
    fallback_key = _resolve_api_key(model, base_url)
    key_candidates = _api_key_candidates(model, base_url)
    if fallback_key and all(k != fallback_key for _, k in key_candidates):
        key_candidates.insert(0, ("resolved", fallback_key))

    if not key_candidates:
        raise RuntimeError("API key is empty. Configure API_KEY or provider-specific keys in .env")

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "stream": False,
    }

    last_error = ""
    for key_source, api_key in key_candidates:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("LLM API returned empty choices")
            content = choices[0].get("message", {}).get("content", "") or ""
            finish_reason = choices[0].get("finish_reason") or ""
            return content, finish_reason

        # Retry only on auth failure; other statuses should fail fast.
        last_error = f"{response.status_code} via {key_source}: {response.text[:500]}"
        if response.status_code != 401:
            break

    raise RuntimeError(f"LLM API error {last_error}")


def _chat_completion_with_continuation(
    model: str,
    prompt: str,
    max_tokens: int = 3500,
    max_rounds: int = 6,
    timeout: int = 180,
) -> str:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": "You are a strict log extraction assistant."},
        {"role": "user", "content": prompt},
    ]

    accumulated = ""
    for _ in range(max_rounds):
        chunk, finish_reason = _chat_completion_once(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        if not chunk:
            break

        overlap = _find_overlap_size(accumulated, chunk)
        accumulated += chunk[overlap:]

        if finish_reason != "length":
            break

        messages.append({"role": "assistant", "content": chunk})
        messages.append(
            {
                "role": "user",
                "content": "Continue from the exact next line only. Do not repeat previous content. Keep the same required output format.",
            }
        )

    return accumulated


def _strip_reasoning_blocks(text: str) -> str:
    """Remove explicit reasoning tags sometimes emitted by some models."""
    if not text:
        return text
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _normalize_json_log_entry(entry: Dict) -> str:
    ts = entry.get("timestamp") or entry.get("time") or entry.get("ts") or "unknown_time"
    level = str(entry.get("level", "INFO")).upper()
    message = entry.get("message", "")
    source = entry.get("source") or entry.get("url") or "unknown"
    if isinstance(message, (dict, list)):
        message = json.dumps(message, ensure_ascii=False)
    return f"[{ts}] [{level}] {source} | {message}"


def _collect_console_logs_from_dir(path: Path) -> Tuple[List[str], int]:
    lines: List[str] = []
    raw_count = 0

    # Case A: single file input handled elsewhere.

    # Case B: input is one task dir with console_logs.json.
    direct_console = path / "console_logs.json"
    if direct_console.exists():
        try:
            arr = json.loads(direct_console.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict):
                        lines.append(_normalize_json_log_entry(item))
                        raw_count += 1
        except Exception:
            pass
        return lines, raw_count

    # Case C: project dir with task*/console_logs.json.
    task_dirs = [d for d in path.iterdir() if d.is_dir() and d.name.startswith("task")]
    if task_dirs:
        for task_dir in sorted(task_dirs):
            console_file = task_dir / "console_logs.json"
            if not console_file.exists():
                continue
            try:
                arr = json.loads(console_file.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, dict):
                            lines.append(f"[task={task_dir.name}] {_normalize_json_log_entry(item)}")
                            raw_count += 1
            except Exception:
                continue
        return lines, raw_count

    # Case D: webvoyager_results root dir with project/task layout.
    for project_dir in sorted([d for d in path.iterdir() if d.is_dir()]):
        for task_dir in sorted([d for d in project_dir.iterdir() if d.is_dir() and d.name.startswith("task")]):
            console_file = task_dir / "console_logs.json"
            if not console_file.exists():
                continue
            try:
                arr = json.loads(console_file.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, dict):
                            lines.append(
                                f"[project={project_dir.name} task={task_dir.name}] {_normalize_json_log_entry(item)}"
                            )
                            raw_count += 1
            except Exception:
                continue

    return lines, raw_count


def _read_input_logs(input_path: Path, max_chars: int) -> Tuple[str, int, bool]:
    raw_count = 0

    if input_path.is_file():
        if input_path.suffix.lower() == ".json":
            try:
                arr = json.loads(input_path.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(arr, list):
                    lines = []
                    for item in arr:
                        if isinstance(item, dict):
                            lines.append(_normalize_json_log_entry(item))
                            raw_count += 1
                    text = "\n".join(lines)
                else:
                    text = input_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = input_path.read_text(encoding="utf-8", errors="ignore")
        else:
            text = input_path.read_text(encoding="utf-8", errors="ignore")
            raw_count = text.count("\n") + 1 if text else 0
    else:
        lines, raw_count = _collect_console_logs_from_dir(input_path)
        text = "\n".join(lines)

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    return text, raw_count, truncated


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM extractor for frontend console logs")
    parser.add_argument("--input", required=True, help="Path to console log file or results directory")
    parser.add_argument("--output", required=True, help="Output markdown path")
    parser.add_argument("--model", default=None, help="Model name (default prefers WEBVOYAGER/MINIMAX model)")
    parser.add_argument("--max-chars", type=int, default=180000, help="Max input chars sent to LLM")
    parser.add_argument("--max-tokens", type=int, default=3500, help="Max tokens per completion round")
    parser.add_argument("--max-rounds", type=int, default=6, help="Continuation rounds when output hits token limit")
    args = parser.parse_args()

    workspace_root = Path(__file__).resolve().parent.parent
    _load_env(workspace_root)

    model = (
        args.model
        or os.getenv("WEBVOYAGER_MODEL")
        or os.getenv("MINIMAX_MODEL")
        or os.getenv("DEFAULT_MODEL")
        or "MiniMax-M2.7-highspeed"
    )

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    logs_text, raw_count, truncated = _read_input_logs(input_path, max_chars=args.max_chars)
    if not logs_text.strip():
        raise RuntimeError("No logs loaded from input")

    prompt = PROMPT_TEMPLATE.replace("{paste logs here}", logs_text)
    content = _chat_completion_with_continuation(
        model=model,
        prompt=prompt,
        max_tokens=args.max_tokens,
        max_rounds=args.max_rounds,
    )
    content = _strip_reasoning_blocks(content)

    header = [
        "# Telemetry Brief (LLM Extracted)",
        "",
        f"- Input: {input_path}",
        f"- Raw log entries (approx): {raw_count}",
        f"- Truncated before LLM: {'yes' if truncated else 'no'}",
        f"- Model: {model}",
        f"- Max tokens/round: {args.max_tokens}",
        f"- Continuation rounds: {args.max_rounds}",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(header) + content.strip() + "\n", encoding="utf-8")

    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
