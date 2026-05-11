#!/usr/bin/env python3
"""Dynamic telemetry-driven OpenHands code repair pipeline."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import socket
import urllib.request
import urllib.error

from dotenv import load_dotenv

from model_config import to_openhands_model
from telemetry_sanitizer import render_markdown_report, sanitize_console_logs
from webvoyager_eval import evaluate_task_dir, load_task_results


DEFAULT_MAX_ITERATIONS = 24
DEFAULT_WEBVOYAGER_WORKERS = 2


def _get_webvoyager_worker_count(num_tasks: int) -> int:
    requested = os.getenv("WEBVOYAGER_NUM_WORKERS", str(DEFAULT_WEBVOYAGER_WORKERS))
    try:
        parsed = int(requested)
    except ValueError:
        parsed = DEFAULT_WEBVOYAGER_WORKERS
    return max(1, min(parsed, 4, max(1, num_tasks)))


@contextmanager
def _exclusive_web_stack_lock():
    """Serialize local app startup and WebVoyager runs across launchers."""
    lock_path = Path(os.getenv("PIPELINE_WEB_STACK_LOCK", "/tmp/fullstack_web_stack.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        print(f"[web-lock] Waiting for Web stack lock: {lock_path}")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        print(f"[web-lock] Acquired Web stack lock: {lock_path}")
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            print(f"[web-lock] Released Web stack lock: {lock_path}")


def _guard_backend_process_send_calls(backend_dir: Path) -> List[str]:
    """Guard common generated backend patterns that break plain node starts."""
    modified_files: List[str] = []
    for candidate in sorted(backend_dir.rglob("*.js")):
        try:
            original = candidate.read_text(encoding="utf-8")
        except Exception:
            continue

        updated_lines: List[str] = []
        changed = False
        for line in original.splitlines(keepends=True):
            if "process.send(" not in line or "typeof process.send" in line:
                updated_lines.append(line)
                continue

            newline = "\n" if line.endswith("\n") else ""
            stripped = line.rstrip("\n")
            indent = stripped[: len(stripped) - len(stripped.lstrip())]
            body = stripped.strip()
            updated_lines.append(f'{indent}if (typeof process.send === "function") {body}{newline}')
            changed = True

        updated = "".join(updated_lines)
        normalized = re.sub(
            r"assert\s*\{\s*type\s*:\s*(['\"])json\1\s*\}",
            'with { type: "json" }',
            updated,
        )
        if normalized != updated:
            changed = True
            updated = normalized

        if changed:
            candidate.write_text(updated, encoding="utf-8")
            modified_files.append(str(candidate))

        _materialize_missing_local_data_modules(candidate)

    return modified_files


def _materialize_missing_local_data_modules(source_file: Path) -> None:
    try:
        content = source_file.read_text(encoding="utf-8")
    except Exception:
        return

    pattern = re.compile(r"import\s+\{([^}]+)\}\s+from\s+['\"](\.{1,2}/[^'\"]+data[^'\"]*\.js)['\"]")
    for match in pattern.finditer(content):
        imported_names = [item.strip() for item in match.group(1).split(",") if item.strip()]
        target_path = (source_file.parent / match.group(2)).resolve()
        if target_path.exists():
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        exports: List[str] = []
        for name in imported_names:
            local_name = name.split(" as ", 1)[0].strip()
            if local_name.endswith("s"):
                exports.append(f"export const {local_name} = [];\n")
            else:
                exports.append(f"export const {local_name} = {{}};\n")
        target_path.write_text("".join(exports), encoding="utf-8")


def _load_runtime_env(workspace_root: Path) -> None:
    """Load project env files for standalone script execution."""
    load_dotenv(workspace_root / ".env")
    load_dotenv(workspace_root / "alternative_generation" / ".env")


def _build_openhands_llm_env(env: Dict[str, str]) -> Dict[str, str]:
    """Populate OpenHands-required LLM env vars from existing workspace credentials."""
    out = dict(env)

    if out.get("LLM_API_KEY") and out.get("LLM_MODEL"):
        out.setdefault("LLM_EXTRA_BODY", '{"enable_thinking": false}')
        return out

    # Priority 1: dedicated OpenHands vars already present.
    if out.get("LLM_API_KEY") and not out.get("LLM_MODEL"):
        out["LLM_MODEL"] = to_openhands_model(out.get("PIPELINE_MODEL") or out.get("QWEN_MODEL", "qwen3.5-plus"))
        out.setdefault("LLM_PROVIDER", "openai")
        out.setdefault("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        out.setdefault("LLM_EXTRA_BODY", '{"enable_thinking": false}')
        return out

    # Priority 2: Qwen credentials (preferred for this project).
    qwen_key = out.get("QWEN_API_KEY")
    if qwen_key:
        out["LLM_API_KEY"] = qwen_key
        out["LLM_MODEL"] = to_openhands_model(out.get("PIPELINE_MODEL") or out.get("QWEN_MODEL", "qwen3.5-plus"))
        out["LLM_PROVIDER"] = "openai"
        out["LLM_BASE_URL"] = out.get("QWEN_API_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        out["LLM_EXTRA_BODY"] = '{"enable_thinking": false}'
        return out

    # Priority 3: WebVoyager credentials.
    wv_key = out.get("WEBVOYAGER_API_KEY")
    if wv_key:
        out["LLM_API_KEY"] = wv_key
        out["LLM_MODEL"] = to_openhands_model(out.get("PIPELINE_MODEL") or out.get("QWEN_MODEL", "qwen3.5-plus"))
        out["LLM_PROVIDER"] = "openai"
        out["LLM_BASE_URL"] = out.get("WEBVOYAGER_API_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        out["LLM_EXTRA_BODY"] = '{"enable_thinking": false}'
        return out

    # Priority 4: DeepSeek credentials.
    if out.get("DEEPSEEK_API_KEY"):
        out["LLM_API_KEY"] = out["DEEPSEEK_API_KEY"]
        out["LLM_MODEL"] = out.get("LLM_MODEL") or "deepseek/deepseek-chat"
        out["LLM_PROVIDER"] = "deepseek"
        out["LLM_BASE_URL"] = out.get("DEEPSEEK_API_BASE_URL") or "https://api.deepseek.com"
        out["LLM_EXTRA_BODY"] = '{"enable_thinking": false}'
        return out

    # Priority 4: OpenAI key fallback.
    if out.get("OPENAI_API_KEY"):
        out["LLM_API_KEY"] = out["OPENAI_API_KEY"]
        out["LLM_MODEL"] = out.get("LLM_MODEL") or "openai/gpt-4o"
        out["LLM_PROVIDER"] = "openai"
        out["LLM_BASE_URL"] = out.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        out["LLM_EXTRA_BODY"] = '{"enable_thinking": false}'

    return out


@dataclass
class PipelinePaths:
    source_workspace: Path
    webvoyager_results: Path
    experiment_workspace: Path
    telemetry_report: Path
    openhands_task_file: Path
    webvoyager_v2_results: Path = field(init=False)

    def __post_init__(self):
        self.webvoyager_v2_results = self.experiment_workspace / "webvoyager_v2_results"


def derive_experiment_workspace(source_workspace: Path) -> Path:
    source_name = source_workspace.name
    if source_name.endswith("_AST"):
        experiment_name = source_name[:-4] + "_v2_AST"
    elif source_name.endswith("_LLM"):
        experiment_name = source_name[:-4] + "_v2_LLM"
    else:
        experiment_name = f"{source_name}_v2_experiment"
    return source_workspace.parent / experiment_name


def _run(cmd, cwd: Path, env: Optional[Dict[str, str]] = None, timeout: Optional[int] = None):
    """Run a subprocess, killing the entire process group on timeout to avoid pipe deadlocks."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )
    try:
        stdout_b, stderr_b = proc.communicate(timeout=timeout)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        # Kill the entire process group so child processes release the pipe write ends.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            stdout_b, stderr_b = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_b, stderr_b = b"", b""
        returncode = proc.returncode if proc.returncode is not None else -9

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout=stdout_b.decode(errors="replace") if isinstance(stdout_b, bytes) else (stdout_b or ""),
        stderr=stderr_b.decode(errors="replace") if isinstance(stderr_b, bytes) else (stderr_b or ""),
    )


def _run_stream(cmd, cwd: Path, env: Optional[Dict[str, str]] = None, timeout: Optional[int] = None, prefix: str = ""):
    """Run a subprocess with real-time streaming to stdout while also capturing output."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []

    def _reader(pipe, chunks, tag):
        for line_b in iter(pipe.readline, b""):
            line = line_b.decode(errors="replace")
            chunks.append(line)
            sys.stdout.write(f"{prefix}{tag}{line}")
            sys.stdout.flush()
        pipe.close()

    t_out = threading.Thread(target=_reader, args=(proc.stdout, stdout_chunks, ""), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, stderr_chunks, "[stderr] "), daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    t_out.join(timeout=5)
    t_err.join(timeout=5)

    returncode = proc.returncode if proc.returncode is not None else -9
    if timed_out and returncode == 0:
        returncode = -9

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


def _extract_openhands_conversation_id(stdout_text: str) -> Optional[str]:
    if not stdout_text:
        return None
    patterns = [
        r"Conversation ID\s*:\s*([0-9a-fA-F-]{32,36})",
        r"conversation_id\s*[:=]\s*([0-9a-fA-F-]{32,36})",
    ]
    for pat in patterns:
        m = re.search(pat, stdout_text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip().lower()
    return None


def _resolve_openhands_conversation_dir(conversation_id: str) -> Optional[Path]:
    if not conversation_id:
        return None
    root = Path.home() / ".openhands" / "conversations"
    raw = conversation_id.strip().lower()
    compact = raw.replace("-", "")
    candidates = [raw, compact]
    if len(compact) == 32:
        hyphenated = f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:32]}"
        candidates.append(hyphenated)

    for cid in dict.fromkeys(candidates):
        p = root / cid
        if p.exists() and p.is_dir():
            return p
    return None


def _to_int(value):
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _extract_usage_metrics(base_state: Dict) -> Dict[str, Optional[object]]:
    usage_to_metrics = (((base_state or {}).get("stats") or {}).get("usage_to_metrics") or {})
    metrics_node = usage_to_metrics.get("agent") if isinstance(usage_to_metrics, dict) else None
    if not isinstance(metrics_node, dict):
        metrics_node = None
        if isinstance(usage_to_metrics, dict):
            for _, value in usage_to_metrics.items():
                if isinstance(value, dict) and "accumulated_token_usage" in value:
                    metrics_node = value
                    break

    if not isinstance(metrics_node, dict):
        return {
            "status": "metrics_not_found",
            "accumulated_cost": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
            "total_tokens_with_cache_reasoning": None,
            "llm_call_count": None,
            "max_iterations": _to_int((base_state or {}).get("max_iterations")),
        }

    token_usage = metrics_node.get("accumulated_token_usage") or {}
    prompt_tokens = _to_int(token_usage.get("prompt_tokens"))
    completion_tokens = _to_int(token_usage.get("completion_tokens"))
    cache_read_tokens = _to_int(token_usage.get("cache_read_tokens"))
    cache_write_tokens = _to_int(token_usage.get("cache_write_tokens"))
    reasoning_tokens = _to_int(token_usage.get("reasoning_tokens"))

    total_tokens = None
    if prompt_tokens is not None or completion_tokens is not None:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    total_tokens_with_cache_reasoning = None
    if any(v is not None for v in [prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens]):
        total_tokens_with_cache_reasoning = sum(v or 0 for v in [prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens])

    token_usages = metrics_node.get("token_usages")
    llm_call_count = len(token_usages) if isinstance(token_usages, list) else None

    return {
        "status": "success",
        "accumulated_cost": metrics_node.get("accumulated_cost"),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "total_tokens_with_cache_reasoning": total_tokens_with_cache_reasoning,
        "llm_call_count": llm_call_count,
        "max_iterations": _to_int((base_state or {}).get("max_iterations")),
    }


def _collect_openhands_session_metrics(stdout_text: str) -> Dict[str, Optional[object]]:
    conversation_id = _extract_openhands_conversation_id(stdout_text)
    result: Dict[str, Optional[object]] = {
        "status": "unknown",
        "conversation_id": conversation_id,
        "conversation_dir": None,
        "source_file": None,
        "accumulated_cost": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
        "total_tokens_with_cache_reasoning": None,
        "llm_call_count": None,
        "max_iterations": None,
    }

    if not conversation_id:
        result["status"] = "conversation_id_not_found"
        return result

    conv_dir = _resolve_openhands_conversation_dir(conversation_id)
    if conv_dir is None:
        result["status"] = "conversation_dir_not_found"
        return result

    result["conversation_dir"] = str(conv_dir)
    state_file = conv_dir / "base_state.json"
    if not state_file.exists():
        result["status"] = "base_state_missing"
        return result

    result["source_file"] = str(state_file)
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        result["status"] = "base_state_parse_failed"
        return result

    metrics = _extract_usage_metrics(payload)
    result.update(metrics)
    return result


def phase1_build_telemetry_brief(
    paths: PipelinePaths,
    model: Optional[str] = None,
    max_chars: int = 40000,
    max_tokens: int = 1500,
    max_rounds: int = 2,
    retries_per_model: int = 3,
    retry_backoff_seconds: float = 2.0,
) -> Dict[str, str]:
    """Generate LLM-compressed telemetry brief from webvoyager logs."""
    script = Path(__file__).parent / "llm_telemetry_extractor.py"
    out_file = paths.experiment_workspace / "telemetry_brief.md"
    attempts_log = paths.experiment_workspace / "telemetry_brief_attempts.log"

    model_candidates: List[str] = []
    if model:
        model_candidates.append(model)
    else:
        model_candidates.extend(
            [
                os.getenv("PIPELINE_MODEL", ""),
                os.getenv("QWEN_MODEL", ""),
                os.getenv("WEBVOYAGER_MODEL", ""),
                os.getenv("DEFAULT_MODEL", ""),
                "qwen3.5-plus",
            ]
        )
    model_candidates = [m for m in model_candidates if m]
    # de-duplicate while preserving order
    model_candidates = list(dict.fromkeys(model_candidates))

    total_attempts = max(1, int(retries_per_model)) * max(1, len(model_candidates))
    attempt_no = 0
    last_result = None
    selected_model = model_candidates[0] if model_candidates else ""
    log_chunks: List[str] = []

    for chosen_model in model_candidates:
        for model_try in range(max(1, int(retries_per_model))):
            attempt_no += 1
            selected_model = chosen_model
            cmd = [
                sys.executable,
                str(script),
                "--input",
                str(paths.webvoyager_results),
                "--output",
                str(out_file),
                "--max-chars",
                str(max_chars),
                "--max-tokens",
                str(max_tokens),
                "--max-rounds",
                str(max_rounds),
                "--model",
                chosen_model,
            ]

            result = _run_stream(cmd, cwd=Path(__file__).parent.parent, timeout=1800, prefix="")
            last_result = result

            log_chunks.append(
                "\n".join(
                    [
                        f"=== attempt {attempt_no}/{total_attempts} model={chosen_model} model_try={model_try + 1}/{max(1, int(retries_per_model))} ===",
                        f"returncode: {result.returncode}",
                        "--- stdout ---",
                        result.stdout or "",
                        "--- stderr ---",
                        result.stderr or "",
                    ]
                )
            )

            if result.returncode == 0:
                attempts_log.write_text("\n\n".join(log_chunks) + "\n", encoding="utf-8")
                return {
                    "status": "success",
                    "returncode": str(result.returncode),
                    "telemetry_brief": str(out_file),
                    "selected_model": selected_model,
                    "attempts_used": str(attempt_no),
                    "attempts_total": str(total_attempts),
                    "attempts_log": str(attempts_log),
                    "stdout": (result.stdout or "")[:800],
                    "stderr": (result.stderr or "")[:800],
                }

            if model_try < max(1, int(retries_per_model)) - 1:
                sleep_s = retry_backoff_seconds * (model_try + 1)
                if sleep_s > 0:
                    time.sleep(sleep_s)

    attempts_log.write_text("\n\n".join(log_chunks) + "\n", encoding="utf-8")
    if last_result is None:
        return {
            "status": "failed",
            "returncode": "1",
            "telemetry_brief": str(out_file),
            "selected_model": selected_model,
            "attempts_used": "0",
            "attempts_total": str(total_attempts),
            "attempts_log": str(attempts_log),
            "stdout": "",
            "stderr": "No model candidates available for phase1 brief",
        }

    return {
        "status": "failed",
        "returncode": str(last_result.returncode),
        "telemetry_brief": str(out_file),
        "selected_model": selected_model,
        "attempts_used": str(attempt_no),
        "attempts_total": str(total_attempts),
        "attempts_log": str(attempts_log),
        "stdout": (last_result.stdout or "")[:800],
        "stderr": (last_result.stderr or "")[:800],
    }


def _check_port(port: int) -> bool:
    """Check if port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _kill_port(port: int) -> None:
    """Kill process using port."""
    try:
        result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        if result.stdout.strip():
            for pid in result.stdout.strip().split("\n"):
                try:
                    subprocess.run(["kill", pid], check=True)
                except Exception:
                    pass
    except Exception:
        pass
    time.sleep(1)


def _wait_for_server(url: str, timeout: int = 60) -> bool:
    """Wait for server to be accessible via HTTP."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=5)
            return True
        except urllib.error.HTTPError:
            # 4xx/5xx still means an HTTP server is up and reachable.
            return True
        except (urllib.error.URLError, socket.timeout, OSError):
            # socket.timeout can be raised directly by urlopen (not wrapped in URLError)
            # in some Python versions / network conditions.
            time.sleep(2)
    return False


def _port_listener_pids(port: int) -> set[int]:
    try:
        result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5)
    except Exception:
        return set()
    pids: set[int] = set()
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.add(int(line))
        except ValueError:
            continue
    return pids


def _process_family_pids(root_pid: int) -> set[int]:
    family: set[int] = set()
    queue = [int(root_pid)]

    while queue:
        current = queue.pop(0)
        if current in family:
            continue
        family.add(current)
        try:
            result = subprocess.run(["pgrep", "-P", str(current)], capture_output=True, text=True, timeout=5)
        except Exception:
            continue
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                child_pid = int(line)
            except ValueError:
                continue
            if child_pid not in family:
                queue.append(child_pid)

    return family


def _wait_for_backend_port_owner(process: subprocess.Popen, port: int, timeout: int = 60) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if process.poll() is not None:
            return False
        listener_pids = _port_listener_pids(port)
        if listener_pids:
            family_pids = _process_family_pids(process.pid)
            if listener_pids & family_pids:
                time.sleep(1)
                if process.poll() is None:
                    refreshed_listener_pids = _port_listener_pids(port)
                    refreshed_family_pids = _process_family_pids(process.pid)
                    if refreshed_listener_pids & refreshed_family_pids:
                        return True
                return False
        time.sleep(1)
    return False


def _find_free_port(start_port: int = 3000, max_tries: int = 200) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Unable to find free port starting from {start_port}")


def _detect_backend_runtime_port(backend_dir: Path, default_port: int = 5001) -> int:
    """Infer a backend's hardcoded listen port when it does not honor PORT env."""
    candidate_files = [
        backend_dir / "server.js",
        backend_dir / "server.mjs",
        backend_dir / "app.js",
        backend_dir / "index.js",
        backend_dir / "main.js",
        backend_dir / "server.py",
        backend_dir / "app.py",
        backend_dir / "main.py",
    ]
    patterns = [
        re.compile(r"\b(?:const|let|var)\s+PORT\s*=\s*(\d{4,5})\b"),
        re.compile(r"\bPORT\s*=\s*(\d{4,5})\b"),
        re.compile(r"\.listen\(\s*(\d{4,5})\s*[,)]"),
        re.compile(r"uvicorn\.run\([^\n]*port\s*=\s*(\d{4,5})"),
    ]

    for path in candidate_files:
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern in patterns:
            match = pattern.search(content)
            if match:
                try:
                    return int(match.group(1))
                except (TypeError, ValueError):
                    continue

    return default_port


def _create_webvoyager_task_file(project_id: str, port: int = 3000) -> tuple:
    """Create WebVoyager task file for a project. Returns (task_file, num_tasks)."""
    data_dir = Path(__file__).parent.parent / "data"
    task_file = Path(f"/tmp/webvoyager_task_{project_id}_v2.jsonl")

    with open(data_dir / "test.jsonl", "r") as f:
        for line in f:
            data = json.loads(line.strip())
            if data.get("id") == project_id:
                tasks = []
                for idx, item in enumerate(data.get("ui_instruct", [])):
                    task = {
                        "web_name": f"Generated_Project_{project_id}_v2",
                        "id": f"{project_id}--{idx + 1}",
                        "ques": item.get("task", ""),
                        "web": f"http://127.0.0.1:{port}",
                        "expected_result": item.get("expected_result", ""),
                    }
                    tasks.append(task)

                with open(task_file, "w") as f:
                    for task in tasks:
                        f.write(json.dumps(task) + "\n")
                return task_file, len(tasks)
    return None, 0


def _safe_remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)


def phase0_freeze_source(paths: PipelinePaths) -> Dict[str, str]:
    if not paths.source_workspace.exists():
        raise FileNotFoundError(f"Source workspace not found: {paths.source_workspace}")

    _safe_remove(paths.experiment_workspace)
    shutil.copytree(paths.source_workspace, paths.experiment_workspace, symlinks=True)

    git_ok = True
    git_error = ""
    try:
        _run(["git", "init"], cwd=paths.experiment_workspace)
        _run(["git", "add", "."], cwd=paths.experiment_workspace)
        commit = _run(["git", "commit", "-m", "Initial generation"], cwd=paths.experiment_workspace)
        if commit.returncode != 0 and "nothing to commit" not in (commit.stderr or "").lower():
            git_ok = False
            git_error = (commit.stderr or commit.stdout or "git commit failed").strip()[:500]
    except Exception as exc:
        git_ok = False
        git_error = str(exc)

    return {
        "source_workspace": str(paths.source_workspace),
        "experiment_workspace": str(paths.experiment_workspace),
        "git_frozen": "true" if git_ok else "false",
        "git_error": git_error,
    }


def phase1_build_telemetry_report(paths: PipelinePaths, debounce_seconds: float = 0.8) -> Dict[str, str]:
    if not paths.webvoyager_results.exists():
        raise FileNotFoundError(f"WebVoyager results not found: {paths.webvoyager_results}")

    events = sanitize_console_logs(paths.webvoyager_results, debounce_seconds=debounce_seconds)
    render_markdown_report(events, paths.telemetry_report)

    return {
        "telemetry_report": str(paths.telemetry_report),
        "sanitized_events": str(len(events)),
    }


def _load_test_specs(test_jsonl: Path, project_id: str) -> Optional[Dict]:
    """Load task specification for a given project_id from test.jsonl."""
    if not test_jsonl.exists():
        return None
    try:
        with test_jsonl.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if str(record.get("id", "")).zfill(6) == project_id.zfill(6):
                    return record
    except Exception:
        pass
    return None


def _load_v1_task_results(webvoyager_results: Path) -> List[Dict[str, str]]:
    """Load per-task verdicts using the shared WebVoyager-style evaluator."""
    return load_task_results(webvoyager_results)


def _build_phase2_task(
    prompt_template: Path,
    project_id: Optional[str] = None,
    webvoyager_results: Optional[Path] = None,
    test_specs_file: Optional[Path] = None,
) -> str:
    base = prompt_template.read_text(encoding="utf-8")
    context_section = _build_test_context_section(project_id, webvoyager_results, test_specs_file)
    if context_section:
        return base.strip() + "\n\n" + context_section + "\n"
    return base.strip() + "\n"


def _build_test_context_section(
    project_id: Optional[str],
    webvoyager_results: Optional[Path],
    test_specs_file: Optional[Path],
) -> str:
    """Build a structured context block describing what failed in v1 and what was expected."""
    lines: List[str] = []

    # Load test spec
    spec: Optional[Dict] = None
    if test_specs_file and project_id:
        spec = _load_test_specs(test_specs_file, project_id)

    # Load v1 task results
    v1_results: List[Dict[str, str]] = []
    if webvoyager_results:
        v1_results = _load_v1_task_results(webvoyager_results)

    if not spec and not v1_results:
        return ""

    lines.append("---")
    lines.append("# E2E Test Evidence from v1 Baseline")
    lines.append("")
    lines.append("The following information describes what the application is SUPPOSED to do and")
    lines.append("what actually happened during automated end-to-end testing of the v1 code.")
    lines.append("Use this to identify which features are broken and what needs to be fixed.")
    lines.append("")

    if spec:
        lines.append("## Application Purpose")
        lines.append(spec.get("instruction", "").strip())
        lines.append("")

    if spec and spec.get("ui_instruct"):
        ui_tasks = spec["ui_instruct"]
        lines.append("## Expected Behaviors (from Task Specification)")
        for i, ut in enumerate(ui_tasks, start=1):
            task_text = ut.get("task", "").strip()
            expected = ut.get("expected_result", "").strip()
            lines.append(f"### Expected Test {i}")
            if task_text:
                lines.append(f"**Task:** {task_text}")
            if expected:
                lines.append(f"**Expected Result:** {expected}")
            lines.append("")

    if v1_results:
        # Count failures
        failed = [r for r in v1_results if r["verdict"] == "NO"]
        unknown = [r for r in v1_results if r["verdict"] == "UNKNOWN"]
        passed = [r for r in v1_results if r["verdict"] == "YES"]

        lines.append("## v1 Baseline Test Results")
        lines.append(
            f"Summary: {len(passed)} passed, {len(failed)} failed, {len(unknown)} unknown/timeout"
        )
        lines.append("")

        for r in v1_results:
            verdict_label = r["verdict"]
            if verdict_label == "UNKNOWN":
                verdict_label = "FAILED (agent hit iteration limit without completing task)"
            obs = r["observation"]
            lines.append(f"### {r['task_name']} — {verdict_label}")
            if obs:
                lines.append(f"**Agent observation:** {obs}")
            else:
                lines.append("**Agent observation:** (agent hit iteration limit — could not complete the task at all)")
            lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def phase2_openhands_repair(
    paths: PipelinePaths,
    prompt_template: Path,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    timeout_seconds: int = 3600,
    project_id: Optional[str] = None,
    test_specs_file: Optional[Path] = None,
) -> Dict[str, str]:
    if not prompt_template.exists():
        raise FileNotFoundError(f"Prompt template missing: {prompt_template}")

    task_str = _build_phase2_task(
        prompt_template,
        project_id=project_id,
        webvoyager_results=paths.webvoyager_results,
        test_specs_file=test_specs_file,
    )
    paths.openhands_task_file.write_text(task_str, encoding="utf-8")

    cmd = [
        "openhands",
        "--headless",
        "--always-approve",
        "--override-with-envs",
        "-f",
        str(paths.openhands_task_file.resolve()),
    ]

    env = _build_openhands_llm_env(dict(os.environ))
    env["WORKSPACE_BASE"] = str(paths.experiment_workspace.resolve())
    env["OPENHANDS_MAX_ITERATIONS"] = str(max_iterations)
    env["MAX_ITERATIONS"] = str(max_iterations)
    env["TTY_INTERACTIVE"] = "1"

    result = _run_stream(cmd, cwd=paths.experiment_workspace, env=env, timeout=timeout_seconds, prefix="[openhands] ")

    stdout_file = paths.experiment_workspace / "openhands_repair_stdout.log"
    stderr_file = paths.experiment_workspace / "openhands_repair_stderr.log"
    stdout_file.write_text(result.stdout or "", encoding="utf-8")
    stderr_file.write_text(result.stderr or "", encoding="utf-8")

    metrics = _collect_openhands_session_metrics(result.stdout or "")

    llm_calls = metrics.get("llm_call_count", 0) or 0
    if result.returncode != 0:
        status = "failed"
    elif llm_calls == 0:
        # OpenHands exited cleanly but made no LLM calls — likely an auth error
        stdout_text = result.stdout or ""
        if "AuthenticationError" in stdout_text or "login fail" in stdout_text:
            status = "auth_error"
        else:
            status = "no_llm_calls"
    else:
        status = "success"
    payload = {
        "status": status,
        "returncode": str(result.returncode),
        "stdout_log": str(stdout_file),
        "stderr_log": str(stderr_file),
        "max_iterations": str(max_iterations),
        "openhands_conversation_id": metrics.get("conversation_id"),
        "openhands_metrics_status": metrics.get("status"),
        "openhands_total_tokens": metrics.get("total_tokens"),
        "openhands_total_tokens_with_cache_reasoning": metrics.get("total_tokens_with_cache_reasoning"),
        "openhands_prompt_tokens": metrics.get("prompt_tokens"),
        "openhands_completion_tokens": metrics.get("completion_tokens"),
        "openhands_llm_call_count": metrics.get("llm_call_count"),
        "openhands_cost": metrics.get("accumulated_cost"),
        "openhands_metrics_source_file": metrics.get("source_file"),
    }
    return payload


def phase3_webvoyager_test(
    paths: PipelinePaths,
    project_id: str,
    port: int = 3000,
    timeout_seconds: int = 1800,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
) -> Dict[str, str]:
    """Run WebVoyager testing on the repaired code in experiment_workspace."""
    experiment_dir = paths.experiment_workspace
    _safe_remove(paths.webvoyager_v2_results)
    paths.webvoyager_v2_results.mkdir(parents=True, exist_ok=True)

    result = {
        "status": "skipped",
        "message": "",
        "webvoyager_output_dir": str(paths.webvoyager_v2_results),
    }

    backend_process = None
    frontend_process = None
    backend_port = 5001
    frontend_port = port
    web_port = port

    try:
        has_backend = (experiment_dir / "backend").exists()
        has_frontend = (experiment_dir / "frontend").exists()

        if not has_backend and not has_frontend:
            result["status"] = "no_backend_or_frontend"
            result["message"] = "No backend or frontend directory found"
            return result

        with _exclusive_web_stack_lock():
            if has_backend:
                backend_port = _detect_backend_runtime_port(experiment_dir / "backend", default_port=5001)
            _kill_port(5001)
            if backend_port != 5001:
                _kill_port(backend_port)
            _kill_port(port)
            _kill_port(port + 1)

            if has_backend:
                backend_dir = experiment_dir / "backend"
                guarded_files = _guard_backend_process_send_calls(backend_dir)
                if guarded_files:
                    print(f"[web-lock] Guarded unsafe process.send calls in {len(guarded_files)} backend file(s)")
                if not (backend_dir / "node_modules").exists():
                    install_result = _run(
                        ["npm", "install"],
                        cwd=backend_dir,
                        timeout=300,
                    )
                    if install_result.returncode != 0:
                        result["status"] = "backend_npm_install_failed"
                        result["message"] = f"npm install failed: {(install_result.stderr or '')[:500]}"
                        return result

                # Prefer the backend's declared port when it is hardcoded.
                _backend_port = backend_port if has_frontend else backend_port

                if (backend_dir / "server.py").exists():
                    cmd = [sys.executable, "server.py"]
                elif (backend_dir / "server.js").exists():
                    cmd = ["node", "server.js"]
                else:
                    cmd = ["npm", "start"]

                env = dict(os.environ)
                env["PORT"] = str(_backend_port)
                env["HOST"] = "0.0.0.0"

                backend_process = subprocess.Popen(
                    cmd,
                    cwd=backend_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                if not _wait_for_backend_port_owner(backend_process, _backend_port, timeout=60):
                    result["status"] = "backend_not_accessible"
                    result["message"] = (
                        f"Backend did not bind port {_backend_port} as the spawned process family; "
                        f"listeners={sorted(_port_listener_pids(_backend_port))}"
                    )
                    return result

            if has_frontend:
                frontend_dir = experiment_dir / "frontend"
                if not (frontend_dir / "node_modules").exists():
                    install_result = _run(
                        ["npm", "install"],
                        cwd=frontend_dir,
                        timeout=300,
                    )
                    if install_result.returncode != 0:
                        result["status"] = "frontend_npm_install_failed"
                        result["message"] = f"npm install failed: {(install_result.stderr or '')[:500]}"
                        return result

                frontend_ready = False
                frontend_probe_attempts = [(60, False), (90, True)]
                for attempt_index, (probe_timeout, rotate_port) in enumerate(frontend_probe_attempts, start=1):
                    if rotate_port:
                        _kill_port(frontend_port)
                        frontend_port = _find_free_port(frontend_port + 1)
                    else:
                        frontend_port = _find_free_port(port)

                    cmd = ["npm", "run", "dev", "--", "--port", str(frontend_port), "--host", "0.0.0.0", "--strictPort"] if (frontend_dir / "vite.config.js").exists() else ["npm", "start"]
                    if cmd[0] == "npm" and "dev" not in cmd:
                        cmd = ["npm", "run", "dev", "--", "--port", str(frontend_port), "--host", "0.0.0.0", "--strictPort"]

                    frontend_env = dict(os.environ)
                    frontend_env["PORT"] = str(frontend_port)
                    frontend_env["HOST"] = "0.0.0.0"
                    frontend_process = subprocess.Popen(
                        cmd,
                        cwd=frontend_dir,
                        env=frontend_env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )

                    if _wait_for_server(f"http://127.0.0.1:{frontend_port}", timeout=probe_timeout):
                        frontend_ready = True
                        break

                    print(
                        f"[web-lock] Frontend probe attempt {attempt_index}/{len(frontend_probe_attempts)} failed on port {frontend_port} "
                        f"after {probe_timeout}s"
                    )
                    try:
                        frontend_process.terminate()
                        frontend_process.wait(timeout=10)
                    except Exception:
                        frontend_process.kill()
                    frontend_process = None

                if not frontend_ready:
                    result["status"] = "frontend_not_accessible"
                    result["message"] = (
                        f"Frontend did not become accessible after {len(frontend_probe_attempts)} attempts; "
                        f"last port={frontend_port}"
                    )
                    return result

                web_port = frontend_port
            else:
                web_port = backend_port if has_backend else port

            task_file, num_tasks = _create_webvoyager_task_file(project_id, port=web_port)
            if task_file is None or num_tasks == 0:
                result["status"] = "no_tasks"
                result["message"] = f"No WebVoyager tasks found for project {project_id}"
                return result

            webvoyager_output = paths.webvoyager_v2_results
            webvoyager_workers = _get_webvoyager_worker_count(num_tasks)

            api_model = os.getenv("WEBVOYAGER_MODEL", "qwen-vl-max")
            api_base = os.getenv("WEBVOYAGER_API_BASE_URL") or os.getenv("QWEN_API_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            api_key = os.getenv("WEBVOYAGER_API_KEY") or os.getenv("QWEN_API_KEY")
            if not api_key:
                result["status"] = "api_key_missing"
                result["message"] = "WEBVOYAGER_API_KEY or QWEN_API_KEY is not set"
                return result

            cmd = [
                sys.executable,
                "run.py",
                "--test_file",
                str(task_file),
                "--api_key",
                api_key,
                "--api_model",
                api_model,
                "--api_base_url",
                api_base,
                "--output_dir",
                str(webvoyager_output),
                "--headless",
                "--num_workers",
                str(webvoyager_workers),
                "--max_iter",
                str(max_iter),
            ]

            base_dir = Path(__file__).parent.parent / "webvoyager"
            wv_result = _run_stream(
                cmd,
                cwd=base_dir,
                timeout=timeout_seconds,
                prefix="[webvoyager] ",
            )

            (experiment_dir / "webvoyager_v2_stdout.log").write_text(wv_result.stdout or "", encoding="utf-8")
            (experiment_dir / "webvoyager_v2_stderr.log").write_text(wv_result.stderr or "", encoding="utf-8")

            success_count = 0
            failed_count = 0
            if webvoyager_output.exists():
                task_dirs = [d for d in webvoyager_output.iterdir() if d.is_dir() and d.name.startswith("task")]
                for task_dir in task_dirs:
                    try:
                        verdict = evaluate_task_dir(task_dir)
                        if verdict.get("status") == "SUCCESS":
                            success_count += 1
                        else:
                            failed_count += 1
                    except Exception as exc:
                        result["status"] = "evaluation_failed"
                        result["message"] = f"WebVoyager auto evaluation failed for {task_dir.name}: {exc}"
                        return result

            if wv_result.returncode == 0 or success_count > 0:
                result["status"] = "success" if failed_count == 0 else "partial_success"
                result["message"] = f"{success_count} succeeded, {failed_count} failed"
            else:
                result["status"] = "failed"
                result["message"] = f"WebVoyager process failed (returncode={wv_result.returncode})"

            result["success_count"] = success_count
            result["failed_count"] = failed_count
            result["returncode"] = str(wv_result.returncode)
            result["max_iter"] = str(max_iter)

    finally:
        if backend_process:
            try:
                backend_process.terminate()
                backend_process.wait(timeout=10)
            except Exception:
                backend_process.kill()
        if frontend_process:
            try:
                frontend_process.terminate()
                frontend_process.wait(timeout=10)
            except Exception:
                frontend_process.kill()
        _kill_port(frontend_port)
        _kill_port(port)

    return result


def build_paths(source_workspace: Path, webvoyager_results: Path) -> PipelinePaths:
    experiment_workspace = derive_experiment_workspace(source_workspace)
    telemetry_report = experiment_workspace / "telemetry_report.md"
    openhands_task_file = experiment_workspace / "openhands_repair_task.txt"
    return PipelinePaths(
        source_workspace=source_workspace,
        webvoyager_results=webvoyager_results,
        experiment_workspace=experiment_workspace,
        telemetry_report=telemetry_report,
        openhands_task_file=openhands_task_file,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dynamic Telemetry-Driven OpenHands Code Repair Pipeline")
    parser.add_argument("--source-workspace", required=True, help="Path to frozen source workspace (v1)")
    parser.add_argument("--webvoyager-results", required=True, help="Path to OpenClaw/WebVoyager result directory")
    parser.add_argument(
        "--prompt-template",
        default=str(Path(__file__).parent / "prompts" / "evidence_based_optimization_prompt.txt"),
        help="Prompt template for evidence-based OpenHands repair",
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS, help="OpenHands max iterations")
    parser.add_argument("--timeout", type=int, default=5400, help="OpenHands timeout seconds")
    parser.add_argument("--test-specs-file", default=None, help="Path to test.jsonl for task specifications")
    parser.add_argument("--debounce-seconds", type=float, default=0.8, help="Debounce window for interaction events")
    parser.add_argument("--skip-phase2", action="store_true", help="Generate telemetry report only")
    parser.add_argument("--phase2-only", action="store_true", help="Run only Phase2 on existing *_v2_experiment workspace")
    parser.add_argument("--skip-phase3", action="store_true", help="Skip WebVoyager testing after repair")
    parser.add_argument("--phase3-only", action="store_true", help="Run only Phase3 on existing *_v2_experiment workspace")
    parser.add_argument("--experiment-workspace", help="Explicit path to experiment workspace (overrides computed path)")
    parser.add_argument("--webvoyager-timeout", type=int, default=1800, help="WebVoyager testing timeout in seconds")
    parser.add_argument("--webvoyager-max-iter", type=int, default=10, help="WebVoyager max iterations per task")
    parser.add_argument("--port", type=int, default=3000, help="Port for WebVoyager testing server")
    args = parser.parse_args()

    workspace_root = Path(__file__).resolve().parent.parent
    _load_runtime_env(workspace_root)

    source_workspace = Path(args.source_workspace).resolve()
    webvoyager_results = Path(args.webvoyager_results).resolve()
    prompt_template = Path(args.prompt_template).resolve()

    paths = build_paths(source_workspace, webvoyager_results)

    # Override experiment_workspace if explicitly provided
    if args.experiment_workspace:
        paths.experiment_workspace = Path(args.experiment_workspace).resolve()
        paths.webvoyager_v2_results = paths.experiment_workspace / "webvoyager_v2_results"

    summary = {
        "started_at": datetime.now().isoformat(),
        "phase0": {},
        "phase1": {},
        "phase2": {},
        "phase3": {},
    }

    if args.phase2_only:
        if not paths.experiment_workspace.exists():
            raise FileNotFoundError(
                f"Experiment workspace missing for phase2-only mode: {paths.experiment_workspace}"
            )
        summary["phase0"] = {"status": "skipped_phase2_only"}
        summary["phase1"] = {"status": "skipped_phase2_only"}
    elif args.phase3_only:
        if not paths.experiment_workspace.exists():
            raise FileNotFoundError(
                f"Experiment workspace missing for phase3-only mode: {paths.experiment_workspace}"
            )
        summary["phase0"] = {"status": "skipped_phase3_only"}
        summary["phase1"] = {"status": "skipped_phase3_only"}
        summary["phase2"] = {"status": "skipped_phase3_only"}
    else:
        summary["phase0"] = phase0_freeze_source(paths)
        summary["phase1"] = phase1_build_telemetry_report(paths, debounce_seconds=args.debounce_seconds)

    if args.phase3_only:
        summary["phase2"] = {"status": "skipped_phase3_only"}
    elif not args.skip_phase2:
        _project_id = source_workspace.name.replace("project_", "")
        _test_specs = Path(args.test_specs_file).resolve() if args.test_specs_file else None
        summary["phase2"] = phase2_openhands_repair(
            paths=paths,
            prompt_template=prompt_template,
            max_iterations=args.max_iterations,
            timeout_seconds=args.timeout,
            project_id=_project_id,
            test_specs_file=_test_specs,
        )
    else:
        summary["phase2"] = {"status": "skipped"}

    if not args.skip_phase3:
        project_id = source_workspace.name.replace("project_", "")
        _wv_max_iter = getattr(args, "webvoyager_max_iter", 10)
        summary["phase3"] = phase3_webvoyager_test(
            paths=paths,
            project_id=project_id,
            port=args.port,
            timeout_seconds=args.webvoyager_timeout,
            max_iter=_wv_max_iter,
        )
    else:
        summary["phase3"] = {"status": "skipped"}

    summary["finished_at"] = datetime.now().isoformat()

    out = paths.experiment_workspace / "dynamic_repair_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Summary written to: {out}")


if __name__ == "__main__":
    main()
