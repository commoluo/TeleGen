#!/usr/bin/env python3
"""LLM-based frontend console log extractor using a fixed analysis prompt."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


DEFAULT_MAX_CHARS = 40000
DEFAULT_MAX_TOKENS = 1500
DEFAULT_MAX_ROUNDS = 2
DEFAULT_TIMEOUT = 90
MAX_RETAINED_LINES_PER_SCOPE = 30
MAX_FAST_PATH_TIMELINE_ENTRIES = 12

_NORMALIZED_LOG_PATTERN = re.compile(
    r"^(?P<context>(?:\[(?:project|task)=[^\]]+\]\s*)*)"
    r"\[(?P<timestamp>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s+(?P<source>[^|]+?)\s+\|\s+(?P<message>.*)$"
)

_FILE_LINE_PATTERN = re.compile(r"([\w./\\-]+\.[jt]sx?|[\w./\\-]+\.vue):(\d+)")


def _parse_log_line(line: str) -> Dict[str, str]:
    stripped = line.strip()
    match = _NORMALIZED_LOG_PATTERN.match(stripped)
    if not match:
        return {
            "context": "",
            "timestamp": "unknown_time",
            "level": "INFO",
            "source": "unknown",
            "message": stripped,
        }
    return {
        "context": (match.group("context") or "").strip(),
        "timestamp": (match.group("timestamp") or "unknown_time").strip(),
        "level": (match.group("level") or "INFO").strip().upper(),
        "source": (match.group("source") or "unknown").strip(),
        "message": (match.group("message") or "").strip(),
    }


def _scope_key(parsed: Dict[str, str]) -> str:
    return parsed.get("context") or "global"


def _is_trace_noise(parsed: Dict[str, str]) -> bool:
    return "[trace]" in parsed["message"].lower()


def _is_framework_noise(parsed: Dict[str, str]) -> bool:
    haystack = f"{parsed['source']} {parsed['message']}".lower()
    return any(
        token in haystack
        for token in [
            "node_modules",
            "@vite/client",
            "react devtools",
            "download the react devtools",
            "third-party chunk",
            "chunk-",
            "vite connecting",
            "vite connected",
        ]
    )


def _is_static_asset_noise(parsed: Dict[str, str]) -> bool:
    haystack = f"{parsed['source']} {parsed['message']}".lower()
    if "failed to load resource" not in haystack and "status of 404" not in haystack:
        return False
    return any(
        token in haystack
        for token in [
            "/favicon.ico",
            ".ico",
            ".png",
            ".jpg",
            ".jpeg",
            ".svg",
            ".webp",
            ".css.map",
            ".js.map",
        ]
    )


def _is_error_or_warning(parsed: Dict[str, str]) -> bool:
    haystack = f"{parsed['level']} {parsed['message']}".lower()
    return parsed["level"] in {"SEVERE", "ERROR", "WARN", "WARNING"} or any(
        token in haystack
        for token in [
            " uncaught",
            "exception",
            "traceback",
            "failed",
            "error",
            "cannot ",
            "timeout",
            "status 500",
            "status 404",
            "status 403",
            "status 401",
        ]
    )


def _is_high_signal(parsed: Dict[str, str]) -> bool:
    message_lower = parsed["message"].lower()
    if _is_error_or_warning(parsed):
        return True
    return any(
        token in message_lower
        for token in [
            "[telemetry] interaction",
            "[telemetry] network request",
            "[telemetry] network response",
            "[telemetry] state",
            "click",
            "submit",
            "navigate",
            "input",
            "selected",
            "status=",
            " status ",
        ]
    )


def _dedupe_signature(parsed: Dict[str, str]) -> str:
    message = re.sub(r"\b\d{2}:\d{2}:\d{2}\b", "<time>", parsed["message"].lower())
    message = re.sub(r"\b\d+\b", "<num>", message)
    source = parsed["source"].lower()
    level = parsed["level"].lower()
    return f"{source}|{level}|{message}"


def _preprocess_log_text(raw_text: str) -> Tuple[str, Dict[str, int], List[Dict[str, str]]]:
    stats = {
        "duplicate_entries": 0,
        "trace_noise": 0,
        "framework_noise": 0,
        "other_dropped": 0,
        "retained_entries": 0,
        "error_entries": 0,
        "warning_entries": 0,
        "scopes_trimmed": 0,
    }
    retained_lines: List[str] = []
    retained_parsed: List[Dict[str, str]] = []
    seen_signatures = set()
    per_scope_counts: Dict[str, int] = defaultdict(int)

    for line in raw_text.splitlines():
        if not line.strip():
            continue
        parsed = _parse_log_line(line)
        if _is_trace_noise(parsed):
            stats["trace_noise"] += 1
            continue
        if _is_framework_noise(parsed):
            stats["framework_noise"] += 1
            continue
        if _is_static_asset_noise(parsed):
            stats["framework_noise"] += 1
            continue

        signature = _dedupe_signature(parsed)
        if signature in seen_signatures:
            stats["duplicate_entries"] += 1
            continue
        seen_signatures.add(signature)

        if not _is_high_signal(parsed):
            stats["other_dropped"] += 1
            continue

        scope = _scope_key(parsed)
        if per_scope_counts[scope] >= MAX_RETAINED_LINES_PER_SCOPE:
            stats["scopes_trimmed"] += 1
            continue
        per_scope_counts[scope] += 1

        if parsed["level"] in {"SEVERE", "ERROR"}:
            stats["error_entries"] += 1
        elif parsed["level"] in {"WARN", "WARNING"}:
            stats["warning_entries"] += 1

        retained_lines.append(line.strip())
        retained_parsed.append(parsed)

    stats["retained_entries"] = len(retained_lines)
    return "\n".join(retained_lines), stats, retained_parsed


def _extract_code_locations(lines: List[Dict[str, str]]) -> List[str]:
    locations: List[str] = []
    seen = set()
    for parsed in lines:
        candidates = [parsed["source"], parsed["message"]]
        for candidate in candidates:
            for match in _FILE_LINE_PATTERN.finditer(candidate):
                location = f"{match.group(1)}:{match.group(2)}"
                if location in seen:
                    continue
                seen.add(location)
                locations.append(location)
    return locations


def _classify_fast_path_event(parsed: Dict[str, str]) -> Tuple[str, str]:
    message = parsed["message"]
    message_lower = message.lower()
    if "[telemetry] interaction" in message_lower:
        return "USER_ACTION", message
    if "[telemetry] network request" in message_lower:
        return "API_REQUEST", message
    if "[telemetry] network response" in message_lower:
        return "API_RESPONSE", message
    if parsed["level"] in {"SEVERE", "ERROR", "WARN", "WARNING"}:
        return "ERROR", message
    return "STATE_CHANGE", message


def _build_fast_path_brief(raw_count: int, stats: Dict[str, int], parsed_lines: List[Dict[str, str]]) -> str:
    timeline_lines: List[str] = []
    for parsed in parsed_lines[:MAX_FAST_PATH_TIMELINE_ENTRIES]:
        event_type, description = _classify_fast_path_event(parsed)
        source = parsed["source"] or "unknown"
        timeline_lines.append(f"[{parsed['timestamp']}] {event_type} | {description} | {source}")

    locations = _extract_code_locations(parsed_lines)
    task_context = "Observed limited high-signal frontend telemetry with no critical errors or warnings."
    if any("[telemetry] interaction" in parsed["message"].lower() for parsed in parsed_lines):
        task_context = "The user performed a small number of frontend interactions and no critical errors were retained."

    affected_locations = "\n".join(
        f"- {location} - referenced in retained telemetry"
        for location in locations
    ) or "- none - no source file locations were retained"

    timeline_block = "\n".join(timeline_lines) or "No retained high-signal timeline entries."

    return "\n".join(
        [
            "### Task Context",
            task_context,
            "",
            "### User Operation Timeline",
            timeline_block,
            "",
            "### Error Summary",
            "No SEVERE or warning-level errors were retained after preprocessing.",
            "",
            "### Affected Code Locations",
            affected_locations,
            "",
            "### Compression Report",
            f"- Raw log entries: {raw_count}",
            f"- Retained entries: {stats['retained_entries']}",
            "- Discarded breakdown:",
            f"  - Duplicate entries: {stats['duplicate_entries']}",
            f"  - [TRACE] render noise: {stats['trace_noise']}",
            f"  - Third-party / framework logs: {stats['framework_noise']}",
            f"  - Other: {stats['other_dropped'] + stats['scopes_trimmed']}",
        ]
    )


def _should_use_fast_path(raw_count: int, stats: Dict[str, int], parsed_lines: List[Dict[str, str]]) -> bool:
    if stats["error_entries"] or stats["warning_entries"]:
        return False
    if stats["retained_entries"] == 0:
        return True
    if len(parsed_lines) <= 4:
        return True
    return raw_count <= 25 and len(parsed_lines) <= 8


def _compute_timeout(log_chars: int, base_timeout: int) -> int:
    if log_chars <= 8000:
        return min(base_timeout, 60)
    if log_chars <= 20000:
        return min(base_timeout, 75)
    return base_timeout


def _load_env(workspace_root: Path) -> None:
    load_dotenv(workspace_root / ".env")
    load_dotenv(workspace_root / "alternative_generation" / ".env")


def _infer_provider_from_model(model: str) -> str:
    m = (model or "").lower()
    if "qwen" in m:
        return "qwen"
    if "deepseek" in m:
        return "deepseek"
    return "generic"


def _resolve_api_base_url(model: str) -> str:
    provider = _infer_provider_from_model(model)
    if provider == "qwen":
        return os.getenv("QWEN_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")
    # Default to Qwen/Dashscope endpoint.
    if os.getenv("QWEN_API_KEY") or os.getenv("WEBVOYAGER_API_KEY"):
        return os.getenv("QWEN_API_BASE_URL") or os.getenv("WEBVOYAGER_API_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
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
            provider = "qwen"  # remap to qwen
        elif "dashscope.aliyuncs.com" in url:
            provider = "qwen"

    if provider == "minimax":
        # Legacy: treat as qwen
        return (
            os.getenv("QWEN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("WEBVOYAGER_API_KEY")
            or ""
        )

    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

    if provider == "qwen":
        return (
            os.getenv("QWEN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("WEBVOYAGER_API_KEY")
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
            provider = "qwen"  # remap legacy minimax to qwen
        elif "dashscope.aliyuncs.com" in url:
            provider = "qwen"

    candidates: List[Tuple[str, str]] = []
    if provider == "minimax":
        # Legacy: treat as qwen
        for name in ["QWEN_API_KEY", "DASHSCOPE_API_KEY", "WEBVOYAGER_API_KEY"]:
            val = os.getenv(name)
            if val:
                candidates.append((name, val))
    elif provider == "qwen":
        for name in ["QWEN_API_KEY", "DASHSCOPE_API_KEY", "WEBVOYAGER_API_KEY"]:
            val = os.getenv(name)
            if val:
                candidates.append((name, val))
    elif provider == "deepseek":
        for name in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
            val = os.getenv(name)
            if val:
                candidates.append((name, val))
    else:
        for name in ["API_KEY", "WEBVOYAGER_API_KEY", "QWEN_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
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


def _chat_completion_once(model: str, messages: List[Dict[str, str]], max_tokens: int, timeout: int = DEFAULT_TIMEOUT) -> Tuple[str, str]:
    import sys, time
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
        "extra_body": {"enable_thinking": False},
    }

    last_error = ""
    for key_source, api_key in key_candidates:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = None
        for attempt_index, attempt_timeout in enumerate(dict.fromkeys([timeout, max(timeout, 120)]), start=1):
            try:
                print(
                    f"[extractor] POST {url} (model={model}, key_src={key_source}, timeout={attempt_timeout}s, attempt={attempt_index}) ...",
                    flush=True,
                )
                t0 = time.time()
                response = requests.post(url, headers=headers, json=payload, timeout=attempt_timeout)
                elapsed = time.time() - t0
                print(f"[extractor] Response: {response.status_code} in {elapsed:.1f}s", flush=True)
                break
            except requests.exceptions.ReadTimeout as exc:
                last_error = f"timeout via {key_source}: {exc}"
                if attempt_timeout >= 120:
                    response = None
                    break
                print("[extractor] Read timeout encountered, retrying once with a longer timeout", flush=True)
        if response is None:
            continue
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
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": "You are a strict log extraction assistant."},
        {"role": "user", "content": prompt},
    ]

    accumulated = ""
    for round_i in range(max_rounds):
        print(f"[extractor] API round {round_i + 1}/{max_rounds} ...", flush=True)
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

        print(f"[extractor] Round {round_i + 1} done: finish_reason={finish_reason}, chars={len(chunk)}", flush=True)
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


def _read_input_logs(input_path: Path) -> Tuple[str, int]:
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

    return text, raw_count


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM extractor for frontend console logs")
    parser.add_argument("--input", required=True, help="Path to console log file or results directory")
    parser.add_argument("--output", required=True, help="Output markdown path")
    parser.add_argument("--model", default=None, help="Model name (default: QWEN_MODEL env or qwen3.5-plus)")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="Max preprocessed input chars sent to LLM")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Max tokens per completion round")
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS, help="Continuation rounds when output hits token limit")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Upper bound timeout seconds for one LLM request")
    args = parser.parse_args()

    workspace_root = Path(__file__).resolve().parent.parent
    _load_env(workspace_root)

    model = (
        args.model
        or os.getenv("QWEN_MODEL")
        or os.getenv("WEBVOYAGER_MODEL")
        or os.getenv("DEFAULT_MODEL")
        or "qwen3.5-plus"
    )

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    raw_logs_text, raw_count = _read_input_logs(input_path)
    if not raw_logs_text.strip():
        raise RuntimeError("No logs loaded from input")

    logs_text, compression_stats, retained_parsed = _preprocess_log_text(raw_logs_text)
    if len(logs_text) > args.max_chars:
        logs_text = logs_text[:args.max_chars]
        truncated = True
    else:
        truncated = False

    fast_path_used = _should_use_fast_path(raw_count, compression_stats, retained_parsed)

    print(
        "[extractor] Loaded "
        f"{raw_count} raw entries, retained {compression_stats['retained_entries']} high-signal entries "
        f"({len(logs_text)} chars, truncated={truncated}, fast_path={fast_path_used}) from {input_path}",
        flush=True,
    )

    if fast_path_used:
        content = _build_fast_path_brief(raw_count, compression_stats, retained_parsed)
    else:
        if not logs_text.strip():
            raise RuntimeError("No high-signal logs remained after preprocessing")

        request_timeout = _compute_timeout(len(logs_text), args.timeout)
        print(
            f"[extractor] Calling LLM model={model} max_tokens={args.max_tokens} max_rounds={args.max_rounds} timeout={request_timeout}",
            flush=True,
        )
        prompt = PROMPT_TEMPLATE.replace("{paste logs here}", logs_text)
        content = _chat_completion_with_continuation(
            model=model,
            prompt=prompt,
            max_tokens=args.max_tokens,
            max_rounds=args.max_rounds,
            timeout=request_timeout,
        )
        content = _strip_reasoning_blocks(content)

    header = [
        "# Telemetry Brief (LLM Extracted)",
        "",
        f"- Input: {input_path}",
        f"- Raw log entries (approx): {raw_count}",
        f"- Retained high-signal entries: {compression_stats['retained_entries']}",
        f"- Truncated before LLM: {'yes' if truncated else 'no'}",
        f"- Fast path used: {'yes' if fast_path_used else 'no'}",
        f"- Model: {model}",
        f"- Max tokens/round: {args.max_tokens}",
        f"- Continuation rounds: {args.max_rounds}",
        f"- Duplicate entries removed: {compression_stats['duplicate_entries']}",
        f"- Trace noise removed: {compression_stats['trace_noise']}",
        f"- Framework noise removed: {compression_stats['framework_noise']}",
        f"- Other entries dropped: {compression_stats['other_dropped'] + compression_stats['scopes_trimmed']}",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(header) + content.strip() + "\n", encoding="utf-8")

    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
