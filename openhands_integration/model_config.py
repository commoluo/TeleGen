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


def to_deepseek_model(model: Optional[str]) -> str:
    normalized = normalize_model_name(model)
    if not normalized:
        return ""
    if "/" in normalized:
        return normalized
    return f"deepseek/{normalized}"


def to_direct_api_model(model: Optional[str]) -> str:
    normalized = normalize_model_name(model)
    if not normalized:
        return ""
    provider_prefixes = {"deepseek", "openai", "qwen"}
    if "/" in normalized:
        provider, raw_model = normalized.split("/", 1)
        if provider in provider_prefixes and raw_model:
            return raw_model
    return normalized


def infer_provider(model: Optional[str]) -> str:
    normalized = normalize_model_name(model)
    if not normalized:
        return "openai"
    if "/" in normalized:
        return normalized.split("/", 1)[0] or "openai"
    return "openai"


def apply_unified_model(model: Optional[str], environ: Optional[MutableMapping[str, str]] = None) -> MutableMapping[str, str]:
    """Apply one raw text model without changing WebVoyager's Qwen routing.

    Raw model name examples:
    - deepseek-v4-flash
    - deepseek/deepseek-v4-flash
    """
    target = environ if environ is not None else os.environ
    normalized = normalize_model_name(model)
    if not normalized:
        return target

    target["PIPELINE_MODEL"] = normalized
    target["UNIFIED_MODEL"] = normalized
    target["DEFAULT_MODEL"] = normalized
    target["DEEPSEEK_MODEL"] = normalized.split("/", 1)[1] if normalized.startswith("deepseek/") else normalized
    target["LLM_MODEL"] = to_deepseek_model(normalized)
    target["LLM_PROVIDER"] = "deepseek"
    target.setdefault("WEBVOYAGER_MODEL", "qwen3.5-plus")
    target.setdefault("WEBVOYAGER_EVAL_MODEL", "qwen3.5-plus")
    target.setdefault("QWEN_MODEL", "qwen3.5-plus")
    return target