"""
Task-aware LLM semantic log injector.

This version does not let the model rewrite full files.
Instead, it asks the model to return structured patch operations for each file,
and applies those patches locally with exact-match replacement plus syntax checks.

Usage:
    python llm_log_injector.py --project openhands_generated/project_000002
    python llm_log_injector.py --project openhands_generated/project_000002 --project-id 000002
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openhands_integration.model_config import to_direct_api_model

# Load .env
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


MAX_PATCH_OPS_PER_FILE = 8
MAX_TASKS_IN_PROMPT = 10
DEFAULT_INJECTION_MAX_WORKERS = 4
DISABLE_THINKING_EXTRA_BODY = {"enable_thinking": False}


def infer_project_id(project_path: Path) -> Optional[str]:
    match = re.search(r"project_(\d{6})", str(project_path))
    return match.group(1) if match else None


def load_task_context(project_id: str, test_spec_file: Path) -> Optional[Dict[str, Any]]:
    if not test_spec_file.exists():
        return None

    with test_spec_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("id") == project_id:
                return {
                    "project_id": project_id,
                    "instruction": record.get("instruction", ""),
                    "category": record.get("Category", {}),
                    "ui_instruct": record.get("ui_instruct", []),
                }
    return None


def format_task_context(task_context: Optional[Dict[str, Any]]) -> str:
    if not task_context:
        return "No test-task context available. Infer logging points only from code structure."

    category = task_context.get("category") or {}
    ui_instruct = task_context.get("ui_instruct") or []
    lines = [
        f"Project ID: {task_context.get('project_id', 'unknown')}",
        "Main requirement:",
        task_context.get("instruction", ""),
        "",
        f"Primary category: {category.get('primary_category', 'N/A')}",
        f"Subcategories: {', '.join(category.get('subcategories', [])) or 'N/A'}",
        "",
        "Test tasks and expected behaviors:",
    ]

    for index, item in enumerate(ui_instruct[:MAX_TASKS_IN_PROMPT], start=1):
        task = item.get("task", "")
        expected = item.get("expected_result", "")
        lines.append(f"{index}. Task: {task}")
        if expected:
            lines.append(f"   Expected: {expected}")

    lines.extend(
        [
            "",
            "Use these tasks to infer the likely user journey, navigation path, backend endpoints, and state transitions that should be logged.",
        ]
    )
    return "\n".join(lines)


class LLMClient:
    """LLM client that requests structured patch operations via DeepSeek."""

    def __init__(self, max_retries: int = 2):
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = os.getenv("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")
        self.model = to_direct_api_model(os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
        self.max_retries = max_retries

        self._fallback_api_key = ""
        self._fallback_base_url = ""
        self._fallback_model = ""
        self._use_fallback = False

    def _get_api_config(self):
        """Return (api_key, base_url, model) for the current provider."""
        if self._use_fallback and self._fallback_api_key:
            return self._fallback_api_key, self._fallback_base_url, self._fallback_model
        return self.api_key, self.base_url, self.model

    def request_patch(
        self,
        file_path: Path,
        file_content: str,
        task_context: Optional[Dict[str, Any]] = None,
        is_retry: bool = False,
    ) -> Optional[str]:
        prompt = self._build_prompt(file_path, file_content, task_context, is_retry=is_retry)

        # Keep log injection on DeepSeek; WebVoyager keeps the Qwen multimodal path.
        providers_to_try = ["primary"]

        for provider_label in providers_to_try:
            use_fb = (provider_label == "fallback")
            api_key, base_url, model = (
                (self._fallback_api_key, self._fallback_base_url, self._fallback_model)
                if use_fb
                else (self.api_key, self.base_url, self.model)
            )

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8000,
                "temperature": 0.1,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            url = f"{base_url}/chat/completions"

            transient_error_count = 0
            for attempt in range(self.max_retries + 1):
                try:
                    with httpx.Client(timeout=180.0) as client:
                        response = client.post(url, headers=headers, json=payload)
                        if response.status_code == 429:
                            wait_time = 5 * (attempt + 1)
                            print(f"    Rate limited ({model}), waiting {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        if response.status_code >= 500:
                            transient_error_count += 1
                            wait_time = 3 * (attempt + 1)
                            print(f"    Server error {response.status_code} from {model} (attempt {attempt+1}), waiting {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        response.raise_for_status()
                        result = response.json()
                        message = result["choices"][0]["message"]
                        content = message.get("content", "") or message.get("output", "") or ""
                        content = re.sub(r"<think>[\s\S]*?</think>", "", content)
                        if use_fb and not self._use_fallback:
                            print(f"    Switched to fallback API ({model}) for remaining files")
                            self._use_fallback = True
                        return content.strip()
                except httpx.HTTPStatusError as err:
                    if err.response.status_code == 429:
                        wait_time = 5 * (attempt + 1)
                        print(f"    Rate limited ({model}), waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    if err.response.status_code >= 500:
                        transient_error_count += 1
                        wait_time = 3 * (attempt + 1)
                        print(f"    Server error {err.response.status_code} from {model} (attempt {attempt+1}), waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    print(f"    HTTP error ({model}): {err}")
                    response_text = (err.response.text or "")[:500]
                    if response_text:
                        print(f"    Response body: {response_text}")
                    break
                except (httpx.TimeoutException, httpx.ReadTimeout, TimeoutError) as err:
                    transient_error_count += 1
                    print(f"    Timeout from {model} (attempt {attempt+1}): {err}")
                    continue
                except httpx.TransportError as err:
                    transient_error_count += 1
                    wait_time = 3 * (attempt + 1)
                    print(f"    Transport error from {model} (attempt {attempt+1}): {err}; waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                except Exception as err:
                    print(f"    Error calling API ({model}): {err}")
                    break

            # If all retries failed with transient errors (server errors / timeouts), try next provider
            if transient_error_count > 0:
                print(f"    All retries failed for {model} due to server errors, trying next provider...")
                continue
            break

        print(f"    Failed after trying all providers")
        return None

    def _build_prompt(
        self,
        file_path: Path,
        file_content: str,
        task_context: Optional[Dict[str, Any]],
        is_retry: bool = False,
    ) -> str:
        if file_path.suffix in {".jsx", ".tsx"}:
            language = "React"
        else:
            language = "JavaScript"

        retry_note = "\nRetry mode: previous output was invalid or could not be applied. Every search snippet must be long enough to match exactly once; include surrounding function context for repeated lines." if is_retry else ""
        task_context_text = format_task_context(task_context)

        return f"""You are a code instrumentation assistant for {language}.

Your job is to add telemetry logs that help debug the specific tested product flows.
You must not rewrite the full file.
You must return PATCH OPERATIONS ONLY as JSON.

## Goals
- Use the task descriptions and expected behaviors to infer important user journeys and likely code paths.
- Add logs only at meaningful points for those tested flows: navigation entry points, event handlers, form submissions, fetch/axios requests, route handlers, controller entry points, and critical branch decisions.
- Prefer the telemetry prefixes already used in this repo: [Telemetry] Interaction, [Telemetry] Network Request, [Telemetry] Network Response, [Telemetry] StateChange, [Telemetry] Branch.

## Strict Rules
1. Return exactly one JSON object. No markdown, no prose.
2. JSON schema:
{{
  "operations": [
    {{
      "action": "replace",
      "search": "exact existing snippet from the file",
      "replace": "replacement snippet with added logs",
      "reason": "short reason"
    }}
  ]
}}
3. Every search snippet must appear exactly as-is in the current file and match exactly once. Include enough surrounding code to make repeated lines unique.
4. Keep patches minimal. Do not refactor unrelated logic.
5. Prefer patches that only add logging lines or the smallest structural change required to place logging safely.
6. If this file is not relevant, return {{"operations": []}}.
7. Never invent APIs, routes, or variables not supported by the file.
8. Do not modify imports unless required for a log insertion pattern.
9. Do not remove existing code.
10. At most {MAX_PATCH_OPS_PER_FILE} operations.
{retry_note}

## Project Task Context
{task_context_text}

## Current File
Path: {file_path.as_posix()}

## Current File Content
{file_content}
"""


def extract_json_object(text: str) -> Optional[str]:
    if not text:
        return None

    stripped = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fenced_match:
        stripped = fenced_match.group(1).strip()

    # ── Standard extraction: first { … last matching } ──
    start = stripped.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return stripped[start:index + 1]

    # ── Fallback: model returned JSON-like content without a wrapping object ──
    # Try to locate "operations" and rebuild a valid {"operations": [...]} object.
    ops_idx = stripped.find('"operations"')
    if ops_idx == -1:
        return None

    bracket_idx = stripped.find("[", ops_idx)
    if bracket_idx == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(bracket_idx, len(stripped)):
        char = stripped[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                reconstructed = '{"operations": ' + stripped[bracket_idx:i + 1] + "}"
                try:
                    json.loads(reconstructed)
                    return reconstructed
                except json.JSONDecodeError:
                    return None
    return None


def parse_patch_response(raw_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    payload_text = extract_json_object(raw_text)
    if not payload_text:
        return None, "No JSON object found in model response"

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as err:
        return None, f"Invalid JSON patch payload: {err}"

    if not isinstance(payload, dict):
        return None, "Patch payload must be a JSON object"

    operations = payload.get("operations")
    if not isinstance(operations, list):
        return None, "Patch payload must contain an operations list"

    if len(operations) > MAX_PATCH_OPS_PER_FILE:
        return None, f"Too many operations: {len(operations)}"

    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            return None, f"Operation {index} is not an object"
        if operation.get("action") != "replace":
            return None, f"Operation {index} must use action=replace"
        if not isinstance(operation.get("search"), str) or not operation["search"]:
            return None, f"Operation {index} missing search snippet"
        if not isinstance(operation.get("replace"), str):
            return None, f"Operation {index} missing replacement snippet"

    return payload, None


def apply_patch_operations(content: str, operations: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    updated = content
    for index, operation in enumerate(operations, start=1):
        search = operation["search"]
        replace = operation["replace"]
        occurrences = updated.count(search)
        if occurrences != 1:
            return None, f"Operation {index} search snippet matched {occurrences} times"
        updated = updated.replace(search, replace, 1)
    return updated, None


def validate_js_code(code: str, original_code: str) -> bool:
    if "require(" in original_code and "require(" not in code:
        return False
    if code.count("{") != code.count("}"):
        return False
    if code.count("(") != code.count(")"):
        return False
    if not code.strip():
        return False
    if len(code) < len(original_code) * 0.5:
        return False
    return True


def validate_js_syntax(code: str) -> bool:
    brace_count = 0
    paren_count = 0
    bracket_count = 0

    for line in code.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        for char in stripped:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
            elif char == "(":
                paren_count += 1
            elif char == ")":
                paren_count -= 1
            elif char == "[":
                bracket_count += 1
            elif char == "]":
                bracket_count -= 1

    return brace_count == 0 and paren_count == 0 and bracket_count == 0


class SemanticLogInjector:
    """Inject semantic logs using LLM-generated patch operations."""

    def __init__(self, max_retries: int = 2, max_workers: Optional[int] = None):
        self.llm = LLMClient(max_retries=max_retries)
        self.backup_dir: Optional[Path] = None
        self.patch_dir: Optional[Path] = None
        requested_workers = max_workers or int(os.getenv("INJECTION_MAX_WORKERS", str(DEFAULT_INJECTION_MAX_WORKERS)))
        self.max_workers = max(1, min(requested_workers, 8))

    def inject_to_project(
        self,
        project_path: str,
        task_context: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        test_spec_file: str = "data/test.jsonl",
    ) -> Dict[str, Any]:
        project = Path(project_path)
        if not project.exists():
            return {"status": "error", "message": "Project not found"}

        inferred_project_id = project_id or infer_project_id(project)
        if not task_context and inferred_project_id:
            task_context = load_task_context(inferred_project_id, Path(test_spec_file))

        self.backup_dir = project / ".log_injector_backup"
        self.patch_dir = project / ".llm_log_patches"
        self.backup_dir.mkdir(exist_ok=True)
        self.patch_dir.mkdir(exist_ok=True)

        results: Dict[str, Any] = {
            "project": str(project),
            "project_id": inferred_project_id,
            "timestamp": datetime.now().isoformat(),
            "mode": "llm_patch",
            "scope": "frontend_only",
            "max_workers": self.max_workers,
            "files_processed": 0,
            "files_modified": 0,
            "files_skipped": 0,
            "files_with_patch": 0,
            "errors": [],
            "patch_records": [],
        }

        files_to_process = self._collect_files(project)
        print(f"Found {len(files_to_process)} frontend files to process with max_workers={self.max_workers}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(self._process_file, project, file_path, task_context): file_path
                for file_path in files_to_process
            }
            for future in concurrent.futures.as_completed(future_to_file):
                file_result = future.result()
                results["files_processed"] += 1
                results["files_skipped"] += int(file_result.get("skipped", False))
                results["files_modified"] += int(file_result.get("modified", False))
                results["files_with_patch"] += int(file_result.get("has_patch", False))
                if file_result.get("patch_record"):
                    results["patch_records"].append(file_result["patch_record"])
                if file_result.get("error"):
                    results["errors"].append(file_result["error"])

        if results["errors"]:
            results["status"] = "partial_success" if results["files_with_patch"] else "failed"
        else:
            results["status"] = "completed"
        return results

    def _process_file(
        self,
        project: Path,
        file_path: Path,
        task_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        relative_path = file_path.relative_to(project)
        print(f"  Processing: {relative_path}")
        outcome: Dict[str, Any] = {
            "file": relative_path.as_posix(),
            "modified": False,
            "skipped": False,
            "has_patch": False,
            "patch_record": None,
            "error": None,
        }

        try:
            content = file_path.read_text(encoding="utf-8")
            backup_path = self._backup_file(project, file_path)

            raw_patch = self.llm.request_patch(file_path, content, task_context=task_context)
            if not raw_patch:
                outcome["skipped"] = True
                outcome["error"] = f"LLM failed for {relative_path}"
                return outcome

            retried = False
            patch_payload, patch_error = parse_patch_response(raw_patch)
            if patch_error:
                print(f"    WARNING: {patch_error}, retrying...")
                raw_patch = self.llm.request_patch(file_path, content, task_context=task_context, is_retry=True)
                retried = True
                if not raw_patch:
                    outcome["skipped"] = True
                    outcome["error"] = f"Retry failed for {relative_path}"
                    return outcome
                patch_payload, patch_error = parse_patch_response(raw_patch)

            if patch_error or not patch_payload:
                outcome["skipped"] = True
                outcome["error"] = f"Invalid patch for {relative_path}: {patch_error}"
                return outcome

            operations = patch_payload.get("operations", [])
            if not operations:
                patch_record = {
                    "file": relative_path.as_posix(),
                    "operations": operations,
                }
                self._write_patch_record(relative_path, patch_record)
                outcome["patch_record"] = patch_record
                print("    No relevant patch operations")
                outcome["skipped"] = True
                return outcome

            outcome["has_patch"] = True
            updated_content, apply_error = apply_patch_operations(content, operations)
            if apply_error or updated_content is None:
                print(f"    WARNING: {apply_error}, retrying...")
                raw_patch = self.llm.request_patch(file_path, content, task_context=task_context, is_retry=True)
                retried = True
                if raw_patch:
                    retry_payload, retry_error = parse_patch_response(raw_patch)
                    if retry_error:
                        apply_error = retry_error
                    elif retry_payload:
                        retry_operations = retry_payload.get("operations", [])
                        if not retry_operations:
                            operations = retry_operations
                            patch_payload = retry_payload
                            patch_record = {
                                "file": relative_path.as_posix(),
                                "operations": operations,
                                "retry": True,
                            }
                            self._write_patch_record(relative_path, patch_record)
                            outcome["patch_record"] = patch_record
                            print("    No relevant patch operations")
                            outcome["skipped"] = True
                            return outcome
                        retry_updated, retry_apply_error = apply_patch_operations(content, retry_operations)
                        if retry_apply_error or retry_updated is None:
                            apply_error = retry_apply_error
                        else:
                            patch_payload = retry_payload
                            operations = retry_operations
                            updated_content = retry_updated
                            apply_error = None

                if apply_error or updated_content is None:
                    shutil.copy2(backup_path, file_path)
                    outcome["skipped"] = True
                    outcome["error"] = f"Patch apply failed for {relative_path}: {apply_error}"
                    return outcome

            patch_record = {
                "file": relative_path.as_posix(),
                "operations": operations,
            }
            if retried:
                patch_record["retry"] = True
            self._write_patch_record(relative_path, patch_record)
            outcome["patch_record"] = patch_record

            if not validate_js_code(updated_content, content):
                shutil.copy2(backup_path, file_path)
                outcome["skipped"] = True
                outcome["error"] = f"Patch validation failed for {relative_path}"
                return outcome

            if not validate_js_syntax(updated_content):
                shutil.copy2(backup_path, file_path)
                outcome["skipped"] = True
                outcome["error"] = f"Potential syntax issue in {relative_path}"
                return outcome

            file_path.write_text(updated_content, encoding="utf-8")
            print(f"    Modified: {relative_path}")
            outcome["modified"] = True
            return outcome
        except Exception as err:
            print(f"    ERROR: {err}")
            outcome["skipped"] = True
            outcome["error"] = f"Error processing {relative_path}: {err}"
            return outcome

    def _collect_files(self, project: Path) -> List[Path]:
        files_to_process: List[Path] = []
        frontend_dir = project / "frontend"
        if frontend_dir.exists():
            for extension in ["*.jsx", "*.js", "*.tsx"]:
                for file_path in sorted(frontend_dir.rglob(extension)):
                    file_str = str(file_path)
                    if (
                        "node_modules" not in file_str
                        and ".log_injector_backup" not in file_str
                        and "/dist/" not in file_str
                    ):
                        files_to_process.append(file_path)
        return files_to_process

    def _backup_file(self, project: Path, file_path: Path) -> Path:
        assert self.backup_dir is not None
        relative_path = file_path.relative_to(project)
        backup_path = self.backup_dir / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, backup_path)
        return backup_path

    def _write_patch_record(self, relative_path: Path, patch_record: Dict[str, Any]) -> None:
        assert self.patch_dir is not None
        safe_name = relative_path.as_posix().replace("/", "__") + ".json"
        patch_file = self.patch_dir / safe_name
        patch_file.write_text(json.dumps(patch_record, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Task-aware LLM semantic log injector")
    parser.add_argument("--project", required=True, help="Path to project directory")
    parser.add_argument("--project-id", help="Project ID used to load test.jsonl context")
    parser.add_argument("--test-spec-file", default="data/test.jsonl", help="Path to test.jsonl")
    parser.add_argument("--output", help="Output file for results (optional)")

    args = parser.parse_args()

    print(f"Starting patch-based log injection for: {args.project}")
    print("=" * 60)

    injector = SemanticLogInjector(max_retries=2)
    results = injector.inject_to_project(
        args.project,
        project_id=args.project_id,
        test_spec_file=args.test_spec_file,
    )

    print("=" * 60)
    print("Completed!")
    print(f"  Files processed: {results['files_processed']}")
    print(f"  Files modified: {results['files_modified']}")
    print(f"  Files skipped: {results['files_skipped']}")
    print(f"  Files with patch: {results['files_with_patch']}")
    print(f"  Errors: {len(results['errors'])}")

    if results["errors"]:
        print("\nErrors:")
        for err in results["errors"]:
            print(f"  - {err}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {args.output}")
