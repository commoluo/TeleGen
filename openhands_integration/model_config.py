#!/usr/bin/env python3
"""Helpers for keeping all pipeline LLM calls on one explicit model."""

from __future__ import annotations

import os
from typing import Dict, MutableMapping, Optional


def normalize_model_name(model: Optional[str]) -> str:
    return (model or "").strip()


def to_openhands_model(model: Optional[str]) -> str:
    normalized = normalize_model_name(model)
    if not normalized:
        return ""
    if "/" in normalized:
        return normalized
    return f"openai/{normalized}"


def infer_provider(model: Optional[str]) -> str:
    normalized = normalize_model_name(model)
    if not normalized:
        return "openai"
    if "/" in normalized:
        return normalized.split("/", 1)[0] or "openai"
    return "openai"


def apply_unified_model(model: Optional[str], environ: Optional[MutableMapping[str, str]] = None) -> MutableMapping[str, str]:
    """Apply one raw model name across all pipeline consumers.

    Raw model name examples:
    - qwen3.5-plus
    - qwen-vl-max
    - openai/gpt-4o
    """
    target = environ if environ is not None else os.environ
    normalized = normalize_model_name(model)
    if not normalized:
        return target

    target["PIPELINE_MODEL"] = normalized
    target["UNIFIED_MODEL"] = normalized
    target["DEFAULT_MODEL"] = normalized
    target["QWEN_MODEL"] = normalized
    target["WEBVOYAGER_MODEL"] = normalized
    target["WEBVOYAGER_EVAL_MODEL"] = normalized
    target["LLM_MODEL"] = to_openhands_model(normalized)
    target.setdefault("LLM_PROVIDER", infer_provider(normalized))
    return target