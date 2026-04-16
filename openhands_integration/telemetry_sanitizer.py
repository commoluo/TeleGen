#!/usr/bin/env python3
"""Telemetry sanitization utilities for dynamic repair pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


TELEMETRY_MARKER = "[Telemetry]"
SEVERE_LEVELS = {"SEVERE", "ERROR"}
NON_ESSENTIAL_KEYS = {
    "timestamp",
    "time",
    "ts",
    "_ts",
    "hash",
    "reactFiber",
    "fiberNode",
    "vite_hmr",
    "stack",
}
BUSINESS_KEYS = {
    "url",
    "payload",
    "event",
    "element",
    "method",
    "status",
    "message",
    "endpoint",
    "path",
    "code",
    "response",
}


@dataclass
class SanitizedEvent:
    source_file: str
    task_id: str
    level: str
    kind: str
    message: str
    data: Dict[str, Any]
    count: int = 1


def _try_parse_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                parsed = json.loads(text)
                return _deep_unwrap(parsed)
            except Exception:
                return value
        return value
    if isinstance(value, dict):
        return {k: _deep_unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_unwrap(v) for v in value]
    return value


def _deep_unwrap(value: Any) -> Any:
    cur = value
    for _ in range(3):
        nxt = _try_parse_json(cur)
        if nxt is cur:
            break
        cur = nxt
    return cur


def _extract_level(entry: Dict[str, Any]) -> str:
    level = str(entry.get("level", "")).upper()
    if not level and "ERROR" in str(entry.get("message", "")).upper():
        level = "ERROR"
    return level or "INFO"


def _extract_message(entry: Dict[str, Any]) -> str:
    msg = entry.get("message", "")
    if isinstance(msg, (dict, list)):
        return json.dumps(msg, ensure_ascii=False)
    return str(msg)


def _extract_timestamp(entry: Dict[str, Any]) -> Optional[float]:
    # Accept either epoch milliseconds, epoch seconds, or ISO datetime string.
    for key in ("timestamp", "time", "ts"):
        if key not in entry:
            continue
        raw = entry.get(key)
        if isinstance(raw, (int, float)):
            if raw > 1e12:
                return float(raw) / 1000.0
            return float(raw)
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                continue
            if raw.isdigit():
                val = float(raw)
                if val > 1e12:
                    return val / 1000.0
                return val
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
    return None


def _keep_entry(entry: Dict[str, Any]) -> bool:
    level = _extract_level(entry)
    message = _extract_message(entry)
    if TELEMETRY_MARKER in message:
        return True
    if level in SEVERE_LEVELS:
        return True
    upper = message.upper()
    if "UNCAUGHT" in upper or "TYPEERROR" in upper:
        return True
    if re.search(r"\b(404|500|502|503)\b", upper):
        return True
    return False


def _classify_kind(message: str, level: str) -> str:
    if level in SEVERE_LEVELS:
        return "runtime_error"
    if "[Interaction]" in message:
        return "interaction"
    if "[Network]" in message:
        return "network"
    if TELEMETRY_MARKER in message:
        return "telemetry"
    return "other"


def _compact_data(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    compact: Dict[str, Any] = {}
    for key, value in data.items():
        if key in NON_ESSENTIAL_KEYS:
            continue
        if key in BUSINESS_KEYS:
            compact[key] = value
            continue
        if isinstance(value, dict):
            child = _compact_data(value)
            if child:
                compact[key] = child
    return compact


def _extract_payload(message: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}

    # Merge entry JSON fields first.
    parsed_entry = _deep_unwrap(entry)
    if isinstance(parsed_entry, dict):
        payload.update(_compact_data(parsed_entry))

    # Parse JSON objects embedded in message.
    for match in re.findall(r"\{.*?\}", message):
        try:
            obj = _deep_unwrap(json.loads(match))
            if isinstance(obj, dict):
                payload.update(_compact_data(obj))
        except Exception:
            continue

    return payload


def _iter_console_files(webvoyager_root: Path) -> Iterable[Tuple[str, str, Path]]:
    # Mode A: caller passes one project directory: .../webvoyager_results/000001
    direct_task_dirs = [t for t in webvoyager_root.iterdir() if t.is_dir() and t.name.startswith("task")]
    if direct_task_dirs:
        project_id = webvoyager_root.name
        for task_dir in sorted(direct_task_dirs):
            console_file = task_dir / "console_logs.json"
            if console_file.exists():
                yield project_id, task_dir.name, console_file
        return

    # Mode B: caller passes batch directory: .../webvoyager_results
    for project_dir in sorted([p for p in webvoyager_root.iterdir() if p.is_dir()]):
        for task_dir in sorted([t for t in project_dir.iterdir() if t.is_dir() and t.name.startswith("task")]):
            console_file = task_dir / "console_logs.json"
            if console_file.exists():
                yield project_dir.name, task_dir.name, console_file


def sanitize_console_logs(webvoyager_root: Path, debounce_seconds: float = 0.8) -> List[SanitizedEvent]:
    events: List[SanitizedEvent] = []

    for project_id, task_id, file_path in _iter_console_files(webvoyager_root):
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(raw, list):
            continue

        last_sig: Optional[Tuple[str, str, str]] = None
        last_ts: Optional[float] = None
        last_event: Optional[SanitizedEvent] = None

        for entry in raw:
            if not isinstance(entry, dict):
                continue
            if not _keep_entry(entry):
                continue

            level = _extract_level(entry)
            message = _extract_message(entry)
            kind = _classify_kind(message, level)
            ts = _extract_timestamp(entry)
            payload = _extract_payload(message, entry)

            signature = (task_id, kind, message)
            should_debounce = (
                kind == "interaction"
                and last_sig == signature
                and last_ts is not None
                and ts is not None
                and (ts - last_ts) <= debounce_seconds
                and last_event is not None
            )

            if should_debounce:
                last_event.count += 1
                last_ts = ts
                continue

            evt = SanitizedEvent(
                source_file=str(file_path),
                task_id=f"{project_id}/{task_id}",
                level=level,
                kind=kind,
                message=message,
                data=payload,
                count=1,
            )
            events.append(evt)
            last_sig = signature
            last_ts = ts
            last_event = evt

    return events


def render_markdown_report(events: List[SanitizedEvent], out_file: Path) -> None:
    lines: List[str] = []
    lines.append("# Telemetry Report")
    lines.append("")
    lines.append(f"Total sanitized events: {len(events)}")
    lines.append("")

    if not events:
        lines.append("No telemetry events matched allowlist rules.")
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    lines.append("## Event Timeline")
    lines.append("")

    for idx, evt in enumerate(events, 1):
        lines.append(f"### {idx}. [{evt.level}] {evt.task_id}")
        lines.append(f"- Kind: {evt.kind}")
        if evt.count > 1:
            lines.append(f"- Debounced repeats: {evt.count}")
        lines.append(f"- Message: {evt.message}")
        if evt.data:
            lines.append("- Data:")
            lines.append("```json")
            lines.append(json.dumps(evt.data, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
