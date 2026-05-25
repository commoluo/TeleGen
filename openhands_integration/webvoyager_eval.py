#!/usr/bin/env python3
"""Shared WebVoyager-style auto evaluation helpers.

This module mirrors the original WebVoyager evaluation protocol:
judge each task using the task instruction, the agent's final response,
and the last k screenshots, then emit SUCCESS / NOT SUCCESS.
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from model_config import normalize_model_name


SYSTEM_PROMPT = """As an evaluator, you will be presented with three primary components to assist you in your role:

1. Web Task Instruction: This is a clear and specific directive provided in natural language, detailing the online activity to be carried out. These requirements may include conducting searches, verifying information, comparing prices, checking availability, or any other action relevant to the specified web service (such as Amazon, Apple, ArXiv, BBC News, Booking etc).

2. Result Screenshots: This is a visual representation of the screen showing the result or intermediate state of performing a web task. It serves as visual proof of the actions taken in response to the instruction.

3. Result Response: This is a textual response obtained after the execution of the web task. It serves as textual result in response to the instruction.

-- You DO NOT NEED to interact with web pages or perform actions such as booking flights or conducting searches on websites.
-- You SHOULD NOT make assumptions based on information not presented in the screenshot when comparing it to the instructions.
-- Your primary responsibility is to conduct a thorough assessment of the web task instruction against the outcome depicted in the screenshot and in the response, evaluating whether the actions taken align with the given instructions.
-- NOTE that the instruction may involve more than one task, for example, locating the garage and summarizing the review. Failing to complete either task, such as not providing a summary, should be considered unsuccessful.
-- NOTE that the screenshot is authentic, but the response provided by LLM is generated at the end of web browsing, and there may be discrepancies between the text and the screenshots.
-- Note the difference: 1) Result response may contradict the screenshot, then the content of the screenshot prevails, 2) The content in the Result response is not mentioned on the screenshot, choose to believe the content.

You should elaborate on how you arrived at your final evaluation and then provide a definitive verdict on whether the task has been successfully accomplished, either as 'SUCCESS' or 'NOT SUCCESS'."""


USER_PROMPT = """TASK: <task>
Result Response: <answer>
<num> screenshots at the end: """


def _encode_image(image_path: Path) -> str:
    with image_path.open("rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def _load_messages(task_dir: Path) -> List[Dict[str, Any]]:
    interact_file = task_dir / "interact_messages.json"
    if not interact_file.exists():
        return []
    try:
        data = json.loads(interact_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _extract_task_content(messages: List[Dict[str, Any]]) -> str:
    if len(messages) < 2:
        return ""
    task_info = messages[1].get("content", "")
    if isinstance(task_info, list) and task_info:
        task_info = task_info[0].get("text", "")
    if not isinstance(task_info, str):
        return ""
    match = re.search(r"Now given a task:(.+?)Please interact with", task_info, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_answer_content(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if not isinstance(content, str):
            continue

        if "Action:" in content:
            match = re.search(r"Action:\s*ANSWER[; ]+\[?(.[^\]]*)\]?", content, flags=re.DOTALL)
            if match:
                return match.group(1).strip()

            fallback = re.search(r"Action:\s*(YES|NO|PARTIAL)\b", content, flags=re.IGNORECASE)
            if fallback:
                return fallback.group(1).upper()

        if "ANSWER;" in content:
            answer_text = content[content.find("ANSWER;") + 7 :].strip()
            if answer_text:
                return answer_text

    return ""


def _sorted_screenshots(task_dir: Path) -> List[Path]:
    screenshots: List[Tuple[int, Path]] = []
    for path in task_dir.iterdir():
        if not path.is_file():
            continue
        match = re.fullmatch(r"screenshot(\d+)\.png", path.name)
        if match:
            screenshots.append((int(match.group(1)), path))
    screenshots.sort(key=lambda item: item[0])
    return [path for _, path in screenshots]


def _cache_path(task_dir: Path) -> Path:
    return task_dir / "webvoyager_auto_eval.json"


def _load_cache(task_dir: Path) -> Optional[Dict[str, Any]]:
    cache_file = _cache_path(task_dir)
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _save_cache(task_dir: Path, payload: Dict[str, Any]) -> None:
    cache_file = _cache_path(task_dir)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_client() -> Tuple[OpenAI, str, int]:
    base_url = (
        os.getenv("WEBVOYAGER_EVAL_API_BASE_URL")
        or os.getenv("WEBVOYAGER_API_BASE_URL")
        or os.getenv("QWEN_API_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
    )
    base_url_lower = (base_url or "").lower()

    if "dashscope.aliyuncs.com" in base_url_lower:
        api_key = (
            os.getenv("WEBVOYAGER_EVAL_API_KEY")
            or os.getenv("WEBVOYAGER_API_KEY")
            or os.getenv("QWEN_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
    else:
        api_key = (
            os.getenv("WEBVOYAGER_EVAL_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("WEBVOYAGER_API_KEY")
            or os.getenv("QWEN_API_KEY")
        )
    if not api_key:
        raise RuntimeError(
            "Missing evaluator API key. Set WEBVOYAGER_EVAL_API_KEY, OPENAI_API_KEY, WEBVOYAGER_API_KEY, or QWEN_API_KEY."
        )

    model = normalize_model_name(os.getenv("WEBVOYAGER_EVAL_MODEL") or "qwen3.5-plus")
    max_images = int(os.getenv("WEBVOYAGER_EVAL_MAX_ATTACHED_IMGS", "15"))

    client_kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    return OpenAI(**client_kwargs), model, max_images


def evaluate_task_dir(task_dir: Path, use_cache: bool = True) -> Dict[str, Any]:
    """Evaluate one task dir using the WebVoyager auto-eval protocol."""
    task_dir = Path(task_dir)

    if use_cache:
        cached = _load_cache(task_dir)
        if cached and cached.get("status") in {"SUCCESS", "NOT_SUCCESS", "UNKNOWN"}:
            cached["source"] = "cache"
            return cached

    messages = _load_messages(task_dir)
    if not messages:
        result = {
            "status": "UNKNOWN",
            "task": "",
            "answer": "",
            "evaluator_response": "",
            "reason": "missing_or_invalid_interact_messages",
            "evaluated_at": datetime.now().isoformat(),
        }
        _save_cache(task_dir, result)
        result["source"] = "fresh"
        return result

    task_content = _extract_task_content(messages)
    answer_content = _extract_answer_content(messages)
    if not answer_content:
        result = {
            "status": "NOT_SUCCESS",
            "task": task_content,
            "answer": "",
            "evaluator_response": "",
            "reason": "no_final_answer",
            "evaluated_at": datetime.now().isoformat(),
        }
        _save_cache(task_dir, result)
        result["source"] = "fresh"
        return result

    screenshots = _sorted_screenshots(task_dir)
    if not screenshots:
        result = {
            "status": "UNKNOWN",
            "task": task_content,
            "answer": answer_content,
            "evaluator_response": "",
            "reason": "missing_screenshots",
            "evaluated_at": datetime.now().isoformat(),
        }
        _save_cache(task_dir, result)
        result["source"] = "fresh"
        return result

    client, model, max_images = _build_client()
    chosen = screenshots[-max_images:]

    user_prompt = USER_PROMPT.replace("<task>", task_content)
    user_prompt = user_prompt.replace("<answer>", answer_content)
    user_prompt = user_prompt.replace("<num>", str(len(chosen)))

    content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image_path in chosen:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{_encode_image(image_path)}"},
            }
        )
    content.append({"type": "text", "text": "Your verdict:\n"})

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        max_tokens=1000,
        seed=42,
        temperature=0,
        timeout=120,
        extra_body={"enable_thinking": False},
    )

    evaluator_response = response.choices[0].message.content or ""
    if "NOT SUCCESS" in evaluator_response:
        status = "NOT_SUCCESS"
    elif "SUCCESS" in evaluator_response:
        status = "SUCCESS"
    else:
        status = "UNKNOWN"

    result = {
        "status": status,
        "task": task_content,
        "answer": answer_content,
        "evaluator_response": evaluator_response,
        "reason": "auto_eval",
        "model": model,
        "screenshots_used": [path.name for path in chosen],
        "evaluated_at": datetime.now().isoformat(),
    }
    _save_cache(task_dir, result)
    result["source"] = "fresh"
    return result


def count_successes(results_dir: Path) -> int:
    """Count SUCCESS tasks in a WebVoyager results directory."""
    results_dir = Path(results_dir)
    if not results_dir.exists():
        return 0

    count = 0
    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir() or not task_dir.name.startswith("task"):
            continue
        verdict = evaluate_task_dir(task_dir)
        if verdict.get("status") == "SUCCESS":
            count += 1
    return count


def load_task_results(results_dir: Path) -> List[Dict[str, str]]:
    """Return per-task SUCCESS / NOT_SUCCESS / UNKNOWN results for a results dir."""
    results: List[Dict[str, str]] = []
    results_dir = Path(results_dir)
    if not results_dir.exists():
        return results

    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir() or not task_dir.name.startswith("task"):
            continue
        verdict = evaluate_task_dir(task_dir)
        status = verdict.get("status", "UNKNOWN")
        mapped = "YES" if status == "SUCCESS" else "NO" if status == "NOT_SUCCESS" else "UNKNOWN"
        results.append(
            {
                "task_name": task_dir.name,
                "verdict": mapped,
                "observation": verdict.get("answer", "")[:500],
            }
        )
    return results