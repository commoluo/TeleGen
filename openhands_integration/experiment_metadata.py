#!/usr/bin/env python3
"""Helpers for recording experiment-level metadata in one place per run."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def metadata_path(run_dir: Path) -> Path:
    return Path(run_dir) / "experiment_metadata.json"


def update_run_metadata(run_dir: Path, updates: Dict[str, Any]) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = metadata_path(run_dir)

    current: Dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except Exception:
            current = {}

    if "started_at" not in current:
        current["started_at"] = datetime.now().isoformat()

    merged = _deep_merge(current, updates)
    merged["last_updated_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return path