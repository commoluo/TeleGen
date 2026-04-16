#!/usr/bin/env python3
"""
Batch Pipeline: OpenHands Generation + Log Injection + WebVoyager Testing
========================================================================

Usage:
    python run_batch.py --start 000001 --end 000005
    python run_batch.py --single 000001
    python run_batch.py --start 000001 --end 000100  # Full batch

Output Structure:
    batch_runs/
    └── run_YYYYMMDD_HHMMSS/
        ├── gen_000001/
        │   ├── task.txt
        │   ├── generation_report.json
        │   ├── project_000001/  (generated code with logs)
        │   └── log_injection_report.json
        ├── gen_000002/
        ...
        └── webvoyager_results/
            ├── 000001/
            ├── 000002/
            ...
"""

import os
import sys
import json
import time
import socket
import subprocess
import argparse
import shutil
import platform
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Cross-platform setsid
if platform.system() == 'Windows':
    subprocess_setsid = None  # Not needed on Windows
else:
    subprocess_setsid = os.setsid

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env
env_path = Path(__file__).parent.parent / "alternative_generation" / ".env"
if env_path.exists():
    load_dotenv(env_path)


# ============================================================================
# Helpers
# ============================================================================

def check_port(port):
    """Check if port is in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False  # Port is free
        except OSError:
            return True  # Port is in use


def kill_port(port):
    """Kill process using port"""
    try:
        result = subprocess.run(['lsof', '-ti', f':{port}'], capture_output=True, text=True)
        if result.stdout.strip():
            for pid in result.stdout.strip().split('\n'):
                try:
                    subprocess.run(['kill', pid], check=True)
                    print(f"    Killed PID {pid} on port {port}")
                except:
                    pass
    except:
        pass
    time.sleep(1)


def wait_for_port(port, timeout=60):
    """Wait for port to be ready"""
    start = time.time()
    while time.time() - start < timeout:
        if check_port(port):
            return True
        time.sleep(2)
    return False


def wait_for_server(url, timeout=60):
    """Wait for server to be actually accessible via HTTP"""
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, method='GET')
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status in [200, 301, 302]:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def create_webvoyager_task_file(project_id, port=3000):
    """Create WebVoyager task file for a project"""
    data_dir = Path(__file__).parent.parent / "data"
    task_file = Path(f"/tmp/webvoyager_task_{project_id}.jsonl")

    with open(data_dir / "test.jsonl", 'r') as f:
        for line in f:
            data = json.loads(line.strip())
            if data.get("id") == project_id:
                tasks = []
                for idx, item in enumerate(data.get("ui_instruct", [])):
                    task = {
                        "web_name": f"Generated_Project_{project_id}",
                        "id": f"{project_id}--{idx+1}",
                        "ques": item.get("task", ""),
                        "web": f"http://localhost:{port}",
                        "expected_result": item.get("expected_result", "")
                    }
                    tasks.append(task)

                with open(task_file, 'w') as f:
                    for task in tasks:
                        f.write(json.dumps(task) + '\n')
                return task_file, len(tasks)
    return None, 0


def _load_package_json(directory: Path):
    pkg_file = Path(directory) / "package.json"
    if not pkg_file.exists():
        return {}
    try:
        return json.loads(pkg_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_vite_project(directory: Path) -> bool:
    pkg = _load_package_json(directory)
    scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    deps = pkg.get("dependencies", {}) if isinstance(pkg, dict) else {}
    dev_deps = pkg.get("devDependencies", {}) if isinstance(pkg, dict) else {}

    if "vite" in deps or "vite" in dev_deps:
        return True

    for cmd in scripts.values() if isinstance(scripts, dict) else []:
        if isinstance(cmd, str) and "vite" in cmd:
            return True

    return False


def _verify_node_modules_integrity(directory: Path):
    node_modules = Path(directory) / "node_modules"
    if not node_modules.exists():
        return False, "node_modules missing"

    if _is_vite_project(directory):
        vite_bin = node_modules / ".bin" / "vite"
        vite_cli = node_modules / "vite" / "bin" / "vite.js"
        if not vite_bin.exists() or not vite_cli.exists():
            return False, "vite install appears corrupted (missing .bin/vite or vite.js)"

        # Runtime smoke check: catches broken shims/symlinks such as wrong import paths.
        try:
            probe = subprocess.run(
                ["npm", "exec", "vite", "--version"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe.returncode != 0:
                return False, "vite executable probe failed"
        except Exception:
            return False, "vite executable probe raised exception"

    return True, "ok"


def _clean_node_modules(directory: Path):
    node_modules = Path(directory) / "node_modules"
    lock_file = Path(directory) / "package-lock.json"

    if node_modules.exists():
        shutil.rmtree(node_modules, ignore_errors=True)
    if lock_file.exists():
        lock_file.unlink(missing_ok=True)


def _remove_path(path: Path):
    """Remove file/dir/symlink uniformly."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path, ignore_errors=True)


def _copy_generated_project(src_dir: Path, dst_dir: Path):
    """Copy generated project while preserving symlinks (critical for node_modules/.bin shims)."""
    _remove_path(dst_dir)

    # Preserve symlinks to avoid dereferencing npm bin shims (e.g., .bin/vite).
    shutil.copytree(src_dir, dst_dir, symlinks=True)


def _prepare_output_project(src_dir: Path, dst_dir: Path, reuse_openhands_workspace=False):
    """Prepare output project directory by copy or symlink reuse mode."""
    if reuse_openhands_workspace:
        _remove_path(dst_dir)
        try:
            dst_dir.symlink_to(src_dir, target_is_directory=True)
            return "symlink_reuse"
        except Exception:
            # Fallback keeps pipeline working on filesystems that reject symlinks.
            _copy_generated_project(src_dir, dst_dir)
            return "copy_fallback"

    _copy_generated_project(src_dir, dst_dir)
    return "copy"


def _looks_like_generated_project_root(path: Path):
    """Heuristic check for generated fullstack project root."""
    if not path or not path.exists() or not path.is_dir():
        return False

    has_backend = (path / "backend").exists() and (path / "backend").is_dir()
    has_frontend = (path / "frontend").exists() and (path / "frontend").is_dir()
    return has_backend or has_frontend


def _find_generated_project_source(gen_workspace: Path, project_id: str):
    """Find generated project root in OpenHands workspace with fallback recursive scan."""
    possible_sources = [
        gen_workspace / "workspace" / f"project_{project_id}",
        gen_workspace / "workspace",
        gen_workspace / f"project_{project_id}",
        gen_workspace,
    ]

    for src in possible_sources:
        if _looks_like_generated_project_root(src):
            return src

    candidates = []
    try:
        for backend_dir in gen_workspace.rglob("backend"):
            if not backend_dir.is_dir():
                continue
            parent = backend_dir.parent
            if _looks_like_generated_project_root(parent):
                candidates.append(parent)
    except Exception:
        pass

    if not candidates:
        return None

    def _score(path: Path):
        has_frontend = (path / "frontend").exists()
        depth = len(path.relative_to(gen_workspace).parts) if path != gen_workspace else 0
        name_match = f"project_{project_id}" in path.as_posix()
        return (
            0 if name_match else 1,
            0 if has_frontend else 1,
            depth,
        )

    candidates.sort(key=_score)
    return candidates[0]


def _scan_webvoyager_task_errors(webvoyager_output: Path):
    """Scan task agent logs for hard failures that should force overall WebVoyager failure."""
    if not webvoyager_output.exists():
        return {
            "cannot_access_count": 0,
            "error_count": 0,
            "task_dirs_count": 0,
        }

    task_dirs = [d for d in webvoyager_output.iterdir() if d.is_dir() and d.name.startswith("task")]
    cannot_access_count = 0
    error_count = 0

    for task_dir in task_dirs:
        log_file = task_dir / "agent.log"
        if not log_file.exists():
            continue
        try:
            content = log_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if "Cannot access the website" in content:
            cannot_access_count += 1
        if " - ERROR - " in content:
            error_count += 1

    return {
        "cannot_access_count": cannot_access_count,
        "error_count": error_count,
        "task_dirs_count": len(task_dirs),
    }


def run_npm_install(directory, timeout=300):
    """Run npm install with retries and self-healing for corrupted installs"""
    directory = Path(directory)

    # Fast path: reuse existing dependencies when they are healthy.
    ok, reason = _verify_node_modules_integrity(directory)
    if ok:
        print("    Dependency integrity check passed; reusing existing node_modules")
        return True

    attempts = [
        ["npm", "install", "--no-audit", "--no-fund", "--prefer-offline"],
        ["npm", "install", "--force", "--no-audit", "--no-fund", "--prefer-offline"],
        ["npm", "install", "--legacy-peer-deps", "--no-audit", "--no-fund", "--prefer-offline"],
    ]

    for idx, cmd in enumerate(attempts, 1):
        try:
            result = subprocess.run(cmd, cwd=directory, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                ok, reason = _verify_node_modules_integrity(directory)
                if ok:
                    return True
                print(f"    npm install attempt {idx} produced broken deps: {reason}")
            print(f"    npm install attempt {idx} failed")
        except Exception as e:
            print(f"    npm install attempt {idx} error: {e}")

    # Self-healing fallback: clean node_modules + lock and reinstall once
    print("    Attempting self-heal: clean reinstall dependencies...")
    try:
        _clean_node_modules(directory)
        result = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--prefer-offline"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            ok, reason = _verify_node_modules_integrity(directory)
            if ok:
                print("    Self-heal reinstall succeeded")
                return True
            print(f"    Self-heal reinstall still broken: {reason}")
        else:
            print("    Self-heal reinstall failed")
    except Exception as e:
        print(f"    Self-heal reinstall error: {e}")

    return False


def _build_openhands_task_prompt(project_id, instruction, category, ui_requirements, prep_in_openhands=False):
    """Build OpenHands task prompt. Scheme B uses in-container prep instructions."""
    if prep_in_openhands:
        return f"""You are a professional fullstack developer. Generate a complete, working web application.

## Project ID: {project_id}

## Main Requirement:
{instruction}

## Category Information:
- Primary Category: {category.get('primary_category', 'N/A')}
- Subcategories: {', '.join(category.get('subcategories', []))}

## UI/UX Requirements:
{chr(10).join(ui_requirements)}

## Technical Requirements:
Generate a fullstack application with:
1. Backend (Node.js/Express): RESTful API on port 5001
2. Frontend (React + Vite): on port 3000
3. CORS enabled

## Implementation Steps (MUST COMPLETE ALL):
1. Create project directory structure
2. Generate backend code with Express
3. Generate frontend code with React + Vite
4. Create package.json files with all dependencies
5. Inject semantic logs directly into generated code (NO post-processing)
   - Frontend logs include marker: [TRACE]
   - Backend logs include marker: [DATA]
6. In container workspace, run environment preparation and smoke checks:
   - backend: npm install
   - backend: node --check app.js OR node --check server.js (whichever exists)
   - frontend: npm install
   - frontend: npm run build OR npm run dev -- --host 0.0.0.0 --port 3000 (if build script unavailable)
7. Create environment scripts:
   - backend/setup.sh
   - frontend/setup.sh
8. Write preparation report to project root: openhands_prep_report.json

## openhands_prep_report.json format:
{{
  "prep_in_openhands": true,
  "backend_install": "ok|fail",
  "backend_syntax": "ok|fail",
  "frontend_install": "ok|fail",
  "frontend_build_or_dev": "ok|fail",
  "log_markers_present": true,
  "notes": "short summary"
}}

Generate COMPLETE, WORKING code. No placeholders, TODOs.
"""

    return f"""You are a professional fullstack developer. Generate a complete, working web application.

## IMPORTANT: Do NOT add any logging statements (no console.log, no logger calls)
## The code should be clean without any debug or tracing statements.

## Project ID: {project_id}

## Main Requirement:
{instruction}

## Category Information:
- Primary Category: {category.get('primary_category', 'N/A')}
- Subcategories: {', '.join(category.get('subcategories', []))}

## UI/UX Requirements:
{chr(10).join(ui_requirements)}

## Technical Requirements:
Generate a fullstack application with:
1. Backend (Node.js/Express): RESTful API on port 5001
2. Frontend (React + Vite): on port 3000
3. CORS enabled

## Implementation Steps:
1. Create project directory structure
2. Generate backend code with Express (NO logging statements)
3. Generate frontend code with React + Vite (NO logging statements)
4. Create package.json files with all dependencies
5. Verify code has no syntax errors

Generate COMPLETE, WORKING code. No placeholders, TODOs.
"""


def _has_semantic_log_markers(project_dir: Path) -> bool:
    """Check whether generated code already includes semantic markers used by pipeline."""
    if not project_dir.exists():
        return False

    patterns = ["[TRACE]", "[DATA]"]
    text_file_ext = {".js", ".jsx", ".ts", ".tsx"}

    for p in project_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in text_file_ext:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if any(marker in content for marker in patterns):
            return True
    return False


def _parse_ast_injector_stdout(stdout_text: str):
    """Parse numeric summary from ast_injector output."""
    metrics = {}
    patterns = {
        "files_modified": r"\[INFO\]\s+Files modified:\s*(\d+)",
        "files_skipped": r"\[INFO\]\s+Files skipped:\s*(\d+)",
        "interaction_injected": r"\[INFO\]\s+Interaction logs injected:\s*(\d+)",
        "network_request_injected": r"\[INFO\]\s+Network request logs injected:\s*(\d+)",
        "network_response_injected": r"\[INFO\]\s+Network response logs injected:\s*(\d+)",
        "arrow_wrapped": r"\[INFO\]\s+Arrow functions block-wrapped:\s*(\d+)",
    }

    for key, pat in patterns.items():
        m = re.search(pat, stdout_text or "")
        if m:
            metrics[key] = int(m.group(1))

    return metrics


def run_ast_log_injection(project_dir: Path, base_dir: Path, timeout=300):
    """Run deterministic AST-based telemetry injection script for a single project."""
    script_path = base_dir / "openhands_integration" / "ast_injector.js"
    if not script_path.exists():
        return {
            "status": "ast_script_missing",
            "script": str(script_path),
            "project_dir": str(project_dir),
        }

    # Reuse mode may provide a symlinked project path; resolve to real path so glob scanning works.
    target_project_dir = project_dir.resolve() if project_dir.exists() else project_dir
    cmd = ["node", str(script_path), str(target_project_dir)]

    # Run from the script's own directory so Node resolves node_modules correctly.
    script_cwd = str(script_path.parent)
    try:
        result = subprocess.run(
            cmd,
            cwd=script_cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "ast_injection_timeout",
            "script": str(script_path),
            "project_dir": str(project_dir),
            "timeout_seconds": timeout,
        }
    except Exception as e:
        return {
            "status": "ast_injection_runner_error",
            "error": str(e),
            "script": str(script_path),
            "project_dir": str(project_dir),
        }

    metrics = _parse_ast_injector_stdout(result.stdout or "")
    report = {
        "status": "success" if result.returncode == 0 else "failed",
        "script": str(script_path),
        "project_dir": str(project_dir),
        "project_dir_resolved": str(target_project_dir),
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }
    report.update(metrics)
    return report


def _detect_backend_autotermination_pattern(backend_dir: Path):
    """Detect suspicious backend code that exits inside/near listen callback."""
    findings = []

    if not backend_dir.exists():
        return {
            "detected": False,
            "reason": "backend_dir_missing",
            "findings": findings,
        }

    candidate_files = list(backend_dir.rglob("*.js")) + list(backend_dir.rglob("*.ts"))

    for file_path in candidate_files:
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines):
            if "process.exit(" not in line:
                continue

            window_start = max(0, i - 20)
            window = "\n".join(lines[window_start:i + 1])
            if re.search(r"\blisten\s*\(", window):
                findings.append({
                    "file": str(file_path),
                    "line": i + 1,
                    "snippet": line.strip(),
                })

    return {
        "detected": len(findings) > 0,
        "reason": "process_exit_near_listen" if findings else "none",
        "findings": findings,
    }


def _write_backend_failure_log(project_dir: Path, payload: dict):
    """Persist backend startup/detection failures for post-run diagnosis."""
    log_file = project_dir / "backend_startup_failure_log.txt"
    header = f"Backend startup guard triggered at {datetime.now().isoformat()}\n"
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    log_file.write_text(header + body + "\n", encoding="utf-8")
    return log_file


def _persist_batch_results(batch_run_dir: Path, results: dict):
    """Write current batch results snapshot to disk."""
    with open(batch_run_dir / "batch_results.json", 'w') as f:
        json.dump(results, f, indent=2)


def _extract_openhands_conversation_id(stdout_text: str):
    """Extract OpenHands conversation ID from headless stdout."""
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


def _resolve_openhands_conversation_dir(conversation_id: str):
    """Resolve OpenHands conversation directory by ID (hyphenated or compact)."""
    if not conversation_id:
        return None

    conversations_root = Path.home() / ".openhands" / "conversations"
    raw = conversation_id.strip().lower()
    compact = raw.replace("-", "")

    candidates = [raw, compact]
    if len(compact) == 32:
        hyphenated = f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:32]}"
        candidates.append(hyphenated)

    for cid in dict.fromkeys(candidates):
        path = conversations_root / cid
        if path.exists() and path.is_dir():
            return path
    return None


def _get_nested(obj, *keys):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _to_int(value):
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _extract_usage_from_state_payload(payload: dict):
    """Extract token/cost metrics from one OpenHands state/event payload."""
    if not isinstance(payload, dict):
        return None

    candidate_roots = [payload, _get_nested(payload, "agent_state")]

    for root in candidate_roots:
        if not isinstance(root, dict):
            continue

        usage_to_metrics = _get_nested(root, "stats", "usage_to_metrics")
        if not isinstance(usage_to_metrics, dict):
            continue

        metrics_node = usage_to_metrics.get("agent")
        if not isinstance(metrics_node, dict):
            for _, value in usage_to_metrics.items():
                if isinstance(value, dict) and "accumulated_token_usage" in value:
                    metrics_node = value
                    break

        if not isinstance(metrics_node, dict):
            continue

        token_usage = metrics_node.get("accumulated_token_usage")
        if not isinstance(token_usage, dict):
            continue

        prompt_tokens = _to_int(token_usage.get("prompt_tokens"))
        completion_tokens = _to_int(token_usage.get("completion_tokens"))
        cache_read_tokens = _to_int(token_usage.get("cache_read_tokens"))
        cache_write_tokens = _to_int(token_usage.get("cache_write_tokens"))
        reasoning_tokens = _to_int(token_usage.get("reasoning_tokens"))

        total_tokens = None
        if prompt_tokens is not None or completion_tokens is not None:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        total_tokens_with_cache_reasoning = None
        parts = [prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens]
        if any(v is not None for v in parts):
            total_tokens_with_cache_reasoning = sum(v or 0 for v in parts)

        token_usages = metrics_node.get("token_usages")
        llm_call_count = len(token_usages) if isinstance(token_usages, list) else None

        max_iterations = _to_int(root.get("max_iterations"))
        if max_iterations is None:
            max_iterations = _to_int(_get_nested(payload, "max_iterations"))

        return {
            "accumulated_token_usage": token_usage,
            "accumulated_cost": metrics_node.get("accumulated_cost"),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
            "total_tokens_with_cache_reasoning": total_tokens_with_cache_reasoning,
            "llm_call_count": llm_call_count,
            "max_iterations": max_iterations,
        }

    return None


def _collect_openhands_session_metrics(stdout_text: str):
    """Collect OpenHands token/cost metrics by mapping stdout conversation ID to local persistence files."""
    conversation_id = _extract_openhands_conversation_id(stdout_text)
    result = {
        "status": "unknown",
        "conversation_id": conversation_id,
        "conversation_dir": None,
        "source_file": None,
        "accumulated_token_usage": None,
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

    conversation_dir = _resolve_openhands_conversation_dir(conversation_id)
    if conversation_dir is None:
        result["status"] = "conversation_dir_not_found"
        return result

    result["conversation_dir"] = str(conversation_dir)

    candidate_files = [conversation_dir / "base_state.json"]
    events_dir = conversation_dir / "events"
    if events_dir.exists() and events_dir.is_dir():
        event_files = sorted(events_dir.glob("*.json"), reverse=True)
        candidate_files.extend(event_files)

    for path in candidate_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue

        usage = _extract_usage_from_state_payload(payload)
        if usage is None:
            continue

        result.update(usage)
        result["status"] = "success"
        result["source_file"] = str(path)
        return result

    result["status"] = "metrics_not_found"
    return result


def _to_text(value):
    """Normalize subprocess outputs for JSON serialization."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


# ============================================================================
# Main Pipeline
# ============================================================================

def run_batch(start_id=None, end_id=None, single_id=None, skip_webvoyager=False, prep_in_openhands=True, reuse_openhands_workspace=True):
    """Run batch pipeline"""

    # Setup paths
    base_dir = Path(__file__).parent.parent
    data_dir = base_dir / "data"
    batch_run_dir = base_dir / "batch_runs" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_run_dir.mkdir(parents=True, exist_ok=True)

    print(f"="*60)
    print(f"Batch Pipeline Starting")
    print(f"="*60)
    print(f"Batch output: {batch_run_dir}")
    print(f"Start ID: {start_id}")
    print(f"End ID: {end_id}")
    print(f"Single ID: {single_id}")
    print(f"Prep in OpenHands (Scheme B): {prep_in_openhands}")
    print(f"Reuse OpenHands workspace: {reuse_openhands_workspace}")
    print(f"="*60)

    # Load test data
    projects = []
    with open(data_dir / "test.jsonl", 'r') as f:
        for line in f:
            data = json.loads(line.strip())
            project_id = data.get("id", "")
            if single_id and project_id != single_id:
                continue
            if start_id and project_id < start_id:
                continue
            if end_id and project_id > end_id:
                break
            projects.append(data)

    print(f"Found {len(projects)} projects to process")
    print()

    # Results tracking
    results = {
        "batch_run_dir": str(batch_run_dir),
        "timestamp": datetime.now().isoformat(),
        "total": len(projects),
        "completed": 0,
        "failed": 0,
        "projects": []
    }

    for idx, project in enumerate(projects):
        project_id = project.get("id", "")
        print(f"\n{'='*60}")
        print(f"[{idx+1}/{len(projects)}] Processing: {project_id}")
        print(f"{'='*60}")

        project_dir = batch_run_dir / f"gen_{project_id}"
        project_result = {
            "project_id": project_id,
            "status": "pending",
            "generation_status": None,
            "log_injection_status": None,
            "webvoyager_status": None,
            "openhands_conversation_id": None,
            "openhands_metrics_status": None,
            "openhands_total_tokens": None,
            "openhands_cost": None,
            "openhands_max_iterations": None,
        }

        try:
            # ================================================================
            # Step 1: OpenHands Generation
            # ================================================================
            print(f"\n[Step 1] OpenHands Generation...")

            gen_workspace = base_dir / "openhands_workspace" / f"gen_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            gen_workspace.mkdir(parents=True, exist_ok=True)

            # Build task prompt
            instruction = project.get("instruction", "")
            category = project.get("Category", {})
            ui_instruct = project.get("ui_instruct", [])

            ui_requirements = []
            for item in ui_instruct[:3]:
                task = item.get('task', '')
                expected = item.get('expected_result', '')
                if task:
                    ui_requirements.append(f"- Task: {task}")
                if expected:
                    ui_requirements.append(f"  Expected: {expected}")

            task_prompt = _build_openhands_task_prompt(
                project_id=project_id,
                instruction=instruction,
                category=category,
                ui_requirements=ui_requirements,
                prep_in_openhands=prep_in_openhands,
            )

            task_file = gen_workspace / "task.txt"
            task_file.write_text(task_prompt)

            # Run OpenHands
            cmd = [
                "openhands",
                "--headless",
                "--always-approve",
                "--override-with-envs",
                "-f", str(task_file.resolve()),
            ]

            env = dict(os.environ)
            if "MINIMAX_API_KEY" in env:
                env["LLM_API_KEY"] = env["MINIMAX_API_KEY"]
                env["LLM_MODEL"] = f"openai/{os.getenv('MINIMAX_MODEL', 'MiniMax-M2.7-highspeed')}"
                env["LLM_PROVIDER"] = "openai"
                env["LLM_BASE_URL"] = "https://api.minimaxi.com/v1"
            env["TTY_INTERACTIVE"] = "1"

            result = subprocess.run(
                cmd,
                cwd=str(gen_workspace.resolve()),
                env=env,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 min timeout
            )

            generation_success = result.returncode == 0
            project_result["generation_status"] = "success" if generation_success else "failed"
            print(f"    Generation: {'SUCCESS' if generation_success else 'FAILED'}")

            # Persist raw OpenHands output for diagnosis
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "openhands_stdout.log").write_text(result.stdout or "", encoding="utf-8")
            (project_dir / "openhands_stderr.log").write_text(result.stderr or "", encoding="utf-8")

            # Parse OpenHands native usage metrics from local conversation persistence.
            session_metrics = _collect_openhands_session_metrics(result.stdout or "")
            project_result["openhands_conversation_id"] = session_metrics.get("conversation_id")
            project_result["openhands_metrics_status"] = session_metrics.get("status")
            project_result["openhands_total_tokens"] = session_metrics.get("total_tokens")
            project_result["openhands_cost"] = session_metrics.get("accumulated_cost")
            project_result["openhands_max_iterations"] = session_metrics.get("max_iterations")

            if session_metrics.get("status") == "success":
                print(
                    "    OpenHands usage: "
                    f"prompt={session_metrics.get('prompt_tokens')}, "
                    f"completion={session_metrics.get('completion_tokens')}, "
                    f"total={session_metrics.get('total_tokens')}, "
                    f"cost={session_metrics.get('accumulated_cost')}"
                )
            else:
                print(f"    OpenHands usage: {session_metrics.get('status')}")

            if not generation_success:
                print(f"    Error: {result.stderr[:500] if result.stderr else 'Unknown error'}")

                with open(project_dir / "generation_report.json", 'w') as f:
                    json.dump({
                        "project_id": project_id,
                        "status": project_result["generation_status"],
                        "workspace": str(gen_workspace),
                        "output": None,
                        "source": None,
                        "output_mode": None,
                        "timestamp": datetime.now().isoformat(),
                        "openhands_metrics": session_metrics,
                    }, f, indent=2)

                project_result["status"] = "failed"
                results["failed"] += 1
                results["projects"].append(project_result)
                continue

            # Find and copy generated project
            output_project_dir = project_dir / f"project_{project_id}"

            # Search for generated project in current workspace first
            src_dir = _find_generated_project_source(gen_workspace, project_id)

            # Fallback: if current workspace has no code (e.g. OpenHands reused a cached
            # conversation and exited early), scan all historical workspaces for this project.
            if src_dir is None and reuse_openhands_workspace:
                openhands_ws_base = base_dir / "openhands_workspace"
                candidates = sorted(
                    [
                        d for d in openhands_ws_base.iterdir()
                        if d.is_dir() and d.name.startswith(f"gen_{project_id}_")
                        and d != gen_workspace
                        and _looks_like_generated_project_root(_find_generated_project_source(d, project_id) or d)
                    ],
                    key=lambda d: d.name,
                    reverse=True,
                )
                if candidates:
                    best = candidates[0]
                    src_dir = _find_generated_project_source(best, project_id) or best
                    print(f"    Fallback: using existing workspace {best.name}")

            if src_dir:
                output_mode = _prepare_output_project(
                    src_dir,
                    output_project_dir,
                    reuse_openhands_workspace=reuse_openhands_workspace,
                )
                if output_mode == "symlink_reuse":
                    print(f"    Reused OpenHands workspace via symlink: {src_dir.name}")
                elif output_mode == "copy_fallback":
                    print(f"    Symlink reuse unavailable; copied project from {src_dir.name}")
                else:
                    print(f"    Copied project from {src_dir.name}")
            else:
                output_mode = "source_not_found"

            # Save generation report
            with open(project_dir / "generation_report.json", 'w') as f:
                json.dump({
                    "project_id": project_id,
                    "status": project_result["generation_status"],
                    "workspace": str(gen_workspace),
                    "output": str(output_project_dir),
                    "source": str(src_dir) if src_dir else None,
                    "output_mode": output_mode,
                    "timestamp": datetime.now().isoformat(),
                    "openhands_metrics": session_metrics,
                }, f, indent=2)

            # ================================================================
            # Step 2: Log Injection
            # ================================================================
            print(f"\n[Step 2] Telemetry Injection...")

            if output_project_dir.exists():
                if prep_in_openhands:
                    prep_report_file = output_project_dir / "openhands_prep_report.json"
                    prep_report = {}
                    if prep_report_file.exists():
                        try:
                            prep_report = json.loads(prep_report_file.read_text(encoding="utf-8"))
                        except Exception:
                            prep_report = {"parse_error": True}

                    has_markers = _has_semantic_log_markers(output_project_dir)
                    if prep_report_file.exists() and has_markers:
                        status = "prepared_in_openhands"
                    elif prep_report_file.exists() and not has_markers:
                        status = "prep_report_found_but_logs_missing"
                    else:
                        status = "prep_report_missing"

                    project_result["log_injection_status"] = status
                    log_result = {
                        "status": status,
                        "prep_in_openhands": True,
                        "prep_report_exists": prep_report_file.exists(),
                        "semantic_log_markers_found": has_markers,
                        "prep_report": prep_report,
                    }
                    print(f"    Container prep verification: {status}")
                    with open(project_dir / "log_injection_report.json", 'w') as f:
                        json.dump(log_result, f, indent=2)
                else:
                    log_result = run_ast_log_injection(output_project_dir, base_dir)
                    project_result["log_injection_status"] = log_result.get("status", "unknown")
                    print(f"    AST injection: {log_result.get('status', 'unknown')}")
                    print(f"    Files modified: {log_result.get('files_modified', 0)}")
                    print(f"    Interaction logs: {log_result.get('interaction_injected', 0)}")
                    print(f"    Network request logs: {log_result.get('network_request_injected', 0)}")
                    print(f"    Network response logs: {log_result.get('network_response_injected', 0)}")

                    with open(project_dir / "log_injection_report.json", 'w') as f:
                        json.dump(log_result, f, indent=2)
            else:
                project_result["log_injection_status"] = "skipped"
                print(f"    Skipped - no project directory")

            # ================================================================
            # Step 3: WebVoyager Testing (if not skipped)
            # ================================================================
            if skip_webvoyager:
                print(f"\n[Step 3] WebVoyager - SKIPPED")
                project_result["status"] = "completed"
                project_result["webvoyager_status"] = "skipped"
            else:
                print(f"\n[Step 3] WebVoyager Testing...")

                # Guard: fail fast when generated backend exits inside listen callback.
                backend_dir = output_project_dir / "backend"
                auto_exit_check = _detect_backend_autotermination_pattern(backend_dir)
                if auto_exit_check.get("detected"):
                    log_file = _write_backend_failure_log(
                        project_dir,
                        {
                            "status": "backend_autotermination_detected",
                            "reason": auto_exit_check.get("reason"),
                            "message": "Detected process.exit(...) near listen(...) in backend source; WebVoyager skipped and marked failed.",
                            "findings": auto_exit_check.get("findings", []),
                        },
                    )
                    print("    Backend auto-termination pattern detected")
                    print(f"    Failure log saved: {log_file}")
                    project_result["status"] = "failed"
                    project_result["webvoyager_status"] = "backend_autotermination_detected"
                    results["failed"] += 1
                    results["projects"].append(project_result)
                    _persist_batch_results(batch_run_dir, results)
                    continue

                # Clean up ports
                kill_port(3000)
                kill_port(5001)

                # Start backend
                if backend_dir.exists():
                    print(f"    Starting backend...")
                    if not run_npm_install(backend_dir):
                        print(f"    Backend npm install failed")
                        log_file = _write_backend_failure_log(
                            project_dir,
                            {
                                "status": "backend_npm_install_failed",
                                "backend_dir": str(backend_dir),
                            },
                        )
                        print(f"    Failure log saved: {log_file}")
                        project_result["status"] = "failed"
                        project_result["webvoyager_status"] = "npm_install_failed"
                        results["failed"] += 1
                        results["projects"].append(project_result)
                        _persist_batch_results(batch_run_dir, results)
                        continue

                    backend_env = dict(os.environ)
                    backend_process = subprocess.Popen(
                        ["npm", "start"],
                        cwd=str(backend_dir),
                        env=backend_env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        preexec_fn=subprocess_setsid
                    )

                    if not wait_for_port(5001, timeout=60):
                        print(f"    Backend failed to start")
                        backend_stdout = ""
                        backend_stderr = ""
                        try:
                            out, err = backend_process.communicate(timeout=2)
                            backend_stdout = _to_text(out)
                            backend_stderr = _to_text(err)
                        except Exception:
                            pass

                        log_file = _write_backend_failure_log(
                            project_dir,
                            {
                                "status": "backend_failed_to_start",
                                "backend_dir": str(backend_dir),
                                "stdout": backend_stdout,
                                "stderr": backend_stderr,
                            },
                        )
                        print(f"    Failure log saved: {log_file}")
                        project_result["status"] = "failed"
                        project_result["webvoyager_status"] = "backend_failed"
                        results["failed"] += 1
                        results["projects"].append(project_result)
                        _persist_batch_results(batch_run_dir, results)
                        continue
                    print(f"    Backend started on port 5001")

                # Start frontend
                frontend_dir = output_project_dir / "frontend"
                if frontend_dir.exists():
                    print(f"    Starting frontend...")
                    if not run_npm_install(frontend_dir):
                        print(f"    Frontend npm install failed")
                        log_file = _write_backend_failure_log(
                            project_dir,
                            {
                                "status": "frontend_npm_install_failed",
                                "frontend_dir": str(frontend_dir),
                            },
                        )
                        print(f"    Failure log saved: {log_file}")
                        project_result["status"] = "failed"
                        project_result["webvoyager_status"] = "npm_install_failed"
                        if backend_dir.exists():
                            kill_port(5001)
                        results["failed"] += 1
                        results["projects"].append(project_result)
                        _persist_batch_results(batch_run_dir, results)
                        continue

                    frontend_env = dict(os.environ)
                    frontend_env['PORT'] = '3000'
                    frontend_process = subprocess.Popen(
                        ["npm", "run", "dev", "--", "--host", "0.0.0.0"],
                        cwd=str(frontend_dir),
                        env=frontend_env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        preexec_fn=subprocess_setsid
                    )

                    if not wait_for_port(3000, timeout=60):
                        print(f"    Frontend failed to start (port not listening)")
                        frontend_stdout = ""
                        frontend_stderr = ""
                        try:
                            out, err = frontend_process.communicate(timeout=2)
                            frontend_stdout = _to_text(out)
                            frontend_stderr = _to_text(err)
                        except Exception:
                            pass

                        log_file = _write_backend_failure_log(
                            project_dir,
                            {
                                "status": "frontend_failed_to_start_port_not_listening",
                                "frontend_dir": str(frontend_dir),
                                "stdout": frontend_stdout,
                                "stderr": frontend_stderr,
                            },
                        )
                        print(f"    Failure log saved: {log_file}")
                        project_result["status"] = "failed"
                        project_result["webvoyager_status"] = "frontend_failed"
                        if backend_dir.exists():
                            kill_port(5001)
                        results["failed"] += 1
                        results["projects"].append(project_result)
                        _persist_batch_results(batch_run_dir, results)
                        continue

                    # Extra check: verify server is actually accessible via HTTP
                    if not wait_for_server("http://localhost:3000", timeout=30):
                        print(f"    Frontend failed to start (not responding to HTTP)")
                        frontend_stdout = ""
                        frontend_stderr = ""
                        try:
                            out, err = frontend_process.communicate(timeout=2)
                            frontend_stdout = _to_text(out)
                            frontend_stderr = _to_text(err)
                        except Exception:
                            pass

                        log_file = _write_backend_failure_log(
                            project_dir,
                            {
                                "status": "frontend_not_accessible_http_check_failed",
                                "frontend_dir": str(frontend_dir),
                                "stdout": frontend_stdout,
                                "stderr": frontend_stderr,
                            },
                        )
                        print(f"    Failure log saved: {log_file}")
                        project_result["status"] = "failed"
                        project_result["webvoyager_status"] = "frontend_not_accessible"
                        if backend_dir.exists():
                            kill_port(5001)
                        results["failed"] += 1
                        results["projects"].append(project_result)
                        _persist_batch_results(batch_run_dir, results)
                        continue
                    print(f"    Frontend started and responding on port 3000")

                # Create task file and run WebVoyager
                task_file, num_tasks = create_webvoyager_task_file(project_id, port=3000)
                if task_file and num_tasks > 0:
                    print(f"    Running WebVoyager ({num_tasks} tasks)...")

                    webvoyager_output = batch_run_dir / "webvoyager_results" / project_id
                    webvoyager_output.mkdir(parents=True, exist_ok=True)

                    # MiniMax-only API config for WebVoyager
                    api_key = (os.getenv("MINIMAX_API_KEY") or "").strip()
                    api_model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
                    api_base = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")

                    if not api_key:
                        print("    WebVoyager: MINIMAX_API_KEY is missing, skipping this project")
                        log_file = _write_backend_failure_log(
                            project_dir,
                            {
                                "status": "minimax_api_key_missing",
                                "message": "MINIMAX_API_KEY is required for WebVoyager run",
                            },
                        )
                        print(f"    Failure log saved: {log_file}")
                        project_result["status"] = "failed"
                        project_result["webvoyager_status"] = "minimax_api_key_missing"
                        if task_file.exists():
                            task_file.unlink()
                        kill_port(3000)
                        kill_port(5001)
                        results["failed"] += 1
                        results["projects"].append(project_result)
                        _persist_batch_results(batch_run_dir, results)
                        continue

                    print(f"    WebVoyager API: model={api_model}, base={api_base}")

                    cmd = [
                        sys.executable, "run.py",
                        "--test_file", str(task_file),
                        "--headless",
                        "--max_iter", "10",
                        "--api_key", api_key,
                        "--api_model", api_model,
                        "--api_base_url", api_base,
                        "--output_dir", str(webvoyager_output),
                        "--window_width", "1024",
                        "--window_height", "768",
                    ]

                    result = subprocess.run(
                        cmd,
                        cwd=str(base_dir / "webvoyager"),
                        capture_output=True,
                        text=True,
                        timeout=600
                    )

                    # Persist raw stdout/stderr for troubleshooting
                    (project_dir / "webvoyager_stdout.log").write_text(result.stdout or "", encoding="utf-8")
                    (project_dir / "webvoyager_stderr.log").write_text(result.stderr or "", encoding="utf-8")

                    # Parse WebVoyager output to check actual results
                    webvoyager_success = False
                    if result.returncode == 0:
                        task_result_dirs = [d for d in webvoyager_output.iterdir() if d.is_dir() and d.name.startswith("task")]

                        if not task_result_dirs:
                            print("    WebVoyager: PROCESS FINISHED but produced no task outputs")

                        # Check stdout for success indicators
                        stdout = result.stdout if result.stdout else ""
                        stderr = result.stderr if result.stderr else ""
                        combined_output = stdout + stderr

                        # Count successful tasks
                        success_count = combined_output.count("completed successfully")
                        failed_count = combined_output.count("failed")

                        task_error_scan = _scan_webvoyager_task_errors(webvoyager_output)
                        cannot_access_count = task_error_scan.get("cannot_access_count", 0)
                        error_count = task_error_scan.get("error_count", 0)

                        print(f"    WebVoyager output: {success_count} succeeded, {failed_count} failed")
                        print(
                            "    WebVoyager task logs: "
                            f"cannot_access={cannot_access_count}, error_logs={error_count}, "
                            f"task_dirs={task_error_scan.get('task_dirs_count', 0)}"
                        )

                        if cannot_access_count > 0:
                            print("    WebVoyager: FAILED (cannot access website detected in task logs)")
                            webvoyager_success = False
                        elif success_count > 0 and failed_count == 0 and task_result_dirs:
                            webvoyager_success = True
                        elif success_count > 0 and task_result_dirs:
                            webvoyager_success = True  # Partial success still counts
                            print(f"    WebVoyager: PARTIAL SUCCESS ({success_count} ok, {failed_count} failed)")
                        else:
                            print(f"    WebVoyager: FAILED (no successful tasks)")
                            if "Cannot access" in combined_output:
                                print(f"    ERROR: Server not accessible")
                    else:
                        print(f"    WebVoyager: PROCESS FAILED (returncode={result.returncode})")
                        print(f"    Error: {result.stderr[:300] if result.stderr else result.stdout[:300]}")

                    project_result["webvoyager_status"] = "success" if webvoyager_success else "failed"

                    # Clean up task file
                    if task_file.exists():
                        task_file.unlink()
                else:
                    project_result["webvoyager_status"] = "no_tasks"

                # Cleanup ports
                kill_port(3000)
                kill_port(5001)

            project_result["status"] = "completed"
            results["completed"] += 1

        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT during processing")
            project_result["status"] = "timeout"
            project_result["generation_status"] = "timeout"
            results["failed"] += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            project_result["status"] = "error"
            project_result["error"] = str(e)
            results["failed"] += 1

        results["projects"].append(project_result)
        print(f"\n    Status: {project_result['status']}")

        # Save intermediate results
        with open(batch_run_dir / "batch_results.json", 'w') as f:
            json.dump(results, f, indent=2)

    # Final summary
    print(f"\n{'='*60}")
    print(f"Batch Complete!")
    print(f"{'='*60}")
    print(f"Total: {results['total']}")
    print(f"Completed: {results['completed']}")
    print(f"Failed: {results['failed']}")
    print(f"Results: {batch_run_dir / 'batch_results.json'}")

    _persist_batch_results(batch_run_dir, results)

    return results


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch: OpenHands + Log Injection + WebVoyager")
    parser.add_argument("--start", help="Start project ID (inclusive)")
    parser.add_argument("--end", help="End project ID (inclusive)")
    parser.add_argument("--single", help="Process only this specific ID")
    parser.add_argument("--skip-webvoyager", action="store_true", help="Skip WebVoyager testing")
    parser.add_argument(
        "--prep-in-openhands",
        action="store_true",
        default=True,
        help="Scheme B: ask OpenHands to perform log injection + env prep inside container; host only verifies and runs WebVoyager",
    )
    parser.add_argument(
        "--no-prep-in-openhands",
        action="store_false",
        dest="prep_in_openhands",
        help="Disable Scheme B and use host-side AST injection flow",
    )
    parser.add_argument(
        "--reuse-openhands-workspace",
        action="store_true",
        default=True,
        help="Reuse generated OpenHands workspace by symlink instead of copying project files",
    )
    parser.add_argument(
        "--no-reuse-openhands-workspace",
        action="store_false",
        dest="reuse_openhands_workspace",
        help="Disable workspace reuse and always copy generated projects",
    )

    args = parser.parse_args()

    if not args.start and not args.end and not args.single:
        parser.error("Must specify --start/--end or --single")

    run_batch(
        start_id=args.start,
        end_id=args.end,
        single_id=args.single,
        skip_webvoyager=args.skip_webvoyager,
        prep_in_openhands=args.prep_in_openhands,
        reuse_openhands_workspace=args.reuse_openhands_workspace,
    )