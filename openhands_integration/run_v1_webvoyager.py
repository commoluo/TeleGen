#!/usr/bin/env python3
"""Run WebVoyager against a CLEAN v1 source (no telemetry logs) for one project.

This is the rebuttal control for the reviewer challenge: "inserting logs into v1
may change the app's behavior and inflate the v1 success rate." The official v1
rate (Flash 0.617 / Pro 0.689) was measured on the instrumented copy
(project_<id>_LLM). This script measures the success rate on the clean copy
(project_<id>, no logs) using the *exact same* serving + WebVoyager + evaluation
path as run_batch.py Phase-1 step 3 (run_batch.py:1447-1771), so the only
difference from the logged run is the absence of injected logs.

No generation, no injection, no repair — only serve(clean) + WV + eval.

Usage:
    python3 openhands_integration/run_v1_webvoyager.py \
        --source-dir <.../gen_000022/project_000022> \
        --project-id 000022 \
        --output-dir  <.../v1_nolog_flash/project_000022/webvoyager_results_nolog/000022>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Import the battle-tested serving + eval helpers directly from run_batch.py so
# behavior matches the logged-v1 run byte-for-byte.
import run_batch as rb  # noqa: E402
from webvoyager_eval import evaluate_task_dir  # noqa: E402

WEBVOYAGER_DIR = HERE.parent / "webvoyager"


def _warmup_chromedriver(project_id: str) -> None:
    """Pre-populate the Selenium Manager chromedriver cache with a single chrome
    session before WebVoyager launches parallel workers.

    WebVoyager runs with --num_workers >= 2; on a cold Selenium Manager cache the
    concurrent first-use races while downloading chromedriver and some tasks fail
    with "Unable to obtain driver for chrome using Selenium Manager". A single
    serial warmup here caches the driver (keyed by chrome version, shared across
    processes via ~/.cache/selenium) so the workers never hit the cold path.
    """
    try:
        from selenium import webdriver
        chrome_bin = os.environ.get("CHROME_BIN") or shutil.which("chromium") or shutil.which("google-chrome")
        opts = webdriver.ChromeOptions()
        if chrome_bin:
            opts.binary_location = chrome_bin
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=opts)
        driver.get("about:blank")
        driver.quit()
        print(f"[v1-nolog:{project_id}] Chromedriver cache warmed ({chrome_bin})")
    except Exception as exc:
        # Non-fatal: WV may still succeed for most tasks; this just reduces flakiness.
        print(f"[v1-nolog:{project_id}] Chromedriver warmup failed (proceeding anyway): {exc}")


def _to_text(value):
    return rb._to_text(value)


def _write_failure_log(output_dir: Path, payload: dict) -> Path:
    log_file = output_dir / "backend_startup_failure_log.txt"
    header = f"Startup guard triggered at {datetime.now().isoformat()}\n"
    log_file.write_text(header + json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return log_file


def _run_wv_subprocess(test_file: Path, output_dir: Path, workers: int, max_iter: int,
                       api_key: str, api_model: str, api_base: str, timeout: int,
                       log_prefix: str, round_idx: int) -> int:
    """Run the WebVoyager run.py subprocess once. Appends stdout/stderr per round."""
    cmd = [
        sys.executable, "run.py",
        "--test_file", str(test_file),
        "--headless",
        "--num_workers", str(workers),
        "--max_iter", str(max_iter),
        "--api_key", api_key,
        "--api_model", api_model,
        "--api_base_url", api_base,
        "--output_dir", str(output_dir),
        "--window_width", "1024",
        "--window_height", "768",
    ]
    res = subprocess.run(cmd, cwd=str(WEBVOYAGER_DIR), capture_output=True, text=True, timeout=timeout)
    mode = "a" if round_idx > 0 else "w"
    with (output_dir / "webvoyager_stdout.log").open(mode, encoding="utf-8") as f:
        f.write(f"\n===== WV round {round_idx} (rc={res.returncode}) =====\n")
        f.write(res.stdout or "")
    with (output_dir / "webvoyager_stderr.log").open(mode, encoding="utf-8") as f:
        f.write(f"\n===== WV round {round_idx} (rc={res.returncode}) =====\n")
        f.write(res.stderr or "")
    print(f"{log_prefix} WV round {round_idx}: rc={res.returncode}")
    return res.returncode


def _task_status(task_dir: Path) -> str:
    """Evaluate one task dir -> status string."""
    try:
        verdict = evaluate_task_dir(task_dir)
        return str(verdict.get("status", "UNKNOWN"))
    except Exception:
        return "EVAL_ERROR"


def _is_infra_failure(status: str, task_dir: Path) -> bool:
    """True for tasks where WebVoyager itself broke (no meaningful output produced),
    as opposed to a genuine pass/fail. These are re-run; genuine NOT_SUCCESS is kept."""
    if status in {"UNKNOWN", "EVAL_ERROR", "MISSING_EVAL"}:
        return True
    # Defensive: no interact messages => agent never ran meaningfully.
    return not (task_dir / "interact_messages.json").exists()


def _write_subset_task_file(project_id: str, task_ids: set[str], port: int):
    """Build a WebVoyager task file containing only the given task ids (`<pid>--<n>`)."""
    wanted = set(task_ids)
    data_dir = HERE.parent / "data"
    out = Path(f"/tmp/webvoyager_retry_{project_id}_{len(task_ids)}.jsonl")
    with open(data_dir / "test.jsonl", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line.strip())
            if data.get("id") != project_id:
                continue
            rows = []
            for idx, item in enumerate(data.get("ui_instruct", [])):
                tid = f"{project_id}--{idx + 1}"
                if tid not in wanted:
                    continue
                rows.append({
                    "web_name": f"Generated_Project_{project_id}",
                    "id": tid,
                    "ques": item.get("task", ""),
                    "web": f"http://127.0.0.1:{port}",
                    "expected_result": item.get("expected_result", ""),
                })
            with open(out, "w", encoding="utf-8") as g:
                for r in rows:
                    g.write(json.dumps(r) + "\n")
            return out, len(rows)
    return None, 0


def run_clean_v1(source_dir: Path, project_id: str, output_dir: Path, max_iter: int = 10,
                 webvoyager_timeout_override: int | None = None) -> dict:
    """Serve the clean v1 app, run WebVoyager, evaluate. Returns a result dict."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = source_dir.resolve()

    print(f"[v1-nolog:{project_id}] clean source: {source_dir}")
    print(f"[v1-nolog:{project_id}] output dir:  {output_dir}")

    result: dict = {
        "project_id": project_id,
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "variant": "nolog",
        "started_at": datetime.now().isoformat(),
        "tasks": {},
        "success_count": 0,
        "failed_count": 0,
        "total_tasks": 0,
        "status": "running",
    }

    backend_dir = source_dir / "backend"
    frontend_dir = source_dir / "frontend"

    backend_runtime_port = 5001
    frontend_runtime_port = 3000
    backend_process = None
    frontend_process = None

    # ------------------------------------------------------------------
    # Guard: fail fast when generated backend exits inside listen callback.
    # ------------------------------------------------------------------
    if backend_dir.exists():
        backend_runtime_port = rb.detect_backend_runtime_port(backend_dir, default_port=5001)
        auto_exit_check = rb._detect_backend_autotermination_pattern(backend_dir)
        if auto_exit_check.get("detected"):
            _write_failure_log(output_dir, {
                "status": "backend_autotermination_detected",
                "reason": auto_exit_check.get("reason"),
                "message": "Detected process.exit(...) near listen(...) in backend source; WebVoyager skipped and marked failed.",
                "findings": auto_exit_check.get("findings", []),
            })
            print(f"[v1-nolog:{project_id}] Backend auto-termination pattern detected; aborting.")
            result.update(status="failed", webvoyager_status="backend_autotermination_detected",
                          finished_at=datetime.now().isoformat())
            _write_summary(output_dir, result)
            return result

    try:
        with rb.exclusive_web_stack_lock():
            # Clean up ports.
            rb.kill_port(3000)
            rb.kill_port(5001)
            if backend_runtime_port != 5001:
                rb.kill_port(backend_runtime_port)

            # ----------------------------------------------------------
            # Start backend (same as run_batch.py:1454-1518).
            # ----------------------------------------------------------
            if backend_dir.exists():
                print(f"[v1-nolog:{project_id}] Starting backend...")
                guarded_files = rb.guard_backend_process_send_calls(backend_dir)
                if guarded_files:
                    print(f"[v1-nolog:{project_id}] Guarded unsafe process.send calls in {len(guarded_files)} backend file(s)")
                if not rb.run_npm_install(backend_dir):
                    _write_failure_log(output_dir, {"status": "backend_npm_install_failed", "backend_dir": str(backend_dir)})
                    result.update(status="failed", webvoyager_status="npm_install_failed",
                                  finished_at=datetime.now().isoformat())
                    _write_summary(output_dir, result)
                    return result

                backend_env = dict(os.environ)
                backend_env["PORT"] = str(backend_runtime_port)
                backend_env["HOST"] = "0.0.0.0"
                if (backend_dir / "server.js").exists():
                    _be_cmd = ["node", "server.js"]
                elif (backend_dir / "index.js").exists():
                    _be_cmd = ["node", "index.js"]
                elif (backend_dir / "app.js").exists():
                    _be_cmd = ["node", "app.js"]
                else:
                    _be_cmd = ["npm", "start"]
                backend_process = subprocess.Popen(
                    _be_cmd,
                    cwd=str(backend_dir),
                    env=backend_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=rb.subprocess_setsid,
                )
                if not rb.wait_for_backend_port_owner(backend_process, backend_runtime_port, timeout=60):
                    print(f"[v1-nolog:{project_id}] Backend failed to start")
                    out, err = b"", b""
                    try:
                        out, err = backend_process.communicate(timeout=2)
                    except Exception:
                        pass
                    _write_failure_log(output_dir, {
                        "status": "backend_failed_to_start",
                        "backend_dir": str(backend_dir),
                        "expected_port": backend_runtime_port,
                        "stdout": _to_text(out),
                        "stderr": _to_text(err),
                    })
                    result.update(status="failed", webvoyager_status="backend_failed",
                                  finished_at=datetime.now().isoformat())
                    _write_summary(output_dir, result)
                    return result
                print(f"[v1-nolog:{project_id}] Backend started on port {backend_runtime_port}")

            # ----------------------------------------------------------
            # Start frontend (same as run_batch.py:1520-1644).
            # ----------------------------------------------------------
            if frontend_dir.exists():
                print(f"[v1-nolog:{project_id}] Starting frontend...")
                if not rb.run_npm_install(frontend_dir):
                    _write_failure_log(output_dir, {"status": "frontend_npm_install_failed", "frontend_dir": str(frontend_dir)})
                    result.update(status="failed", webvoyager_status="npm_install_failed",
                                  finished_at=datetime.now().isoformat())
                    _write_summary(output_dir, result)
                    return result

                frontend_started = False
                frontend_attempts = []
                for frontend_attempt in range(1, 3):
                    if frontend_attempt == 1:
                        frontend_runtime_port = rb.find_free_port(3000)
                    else:
                        rb.kill_port(frontend_runtime_port)
                        frontend_runtime_port = rb.find_free_port(frontend_runtime_port + 1)
                    frontend_env = dict(os.environ)
                    frontend_env["PORT"] = str(frontend_runtime_port)
                    # Vite (chokidar) uses inotify by default; this shared host's
                    # fs.inotify.max_user_instances (128) is saturated by other
                    # containers, which makes vite crash with EMFILE on startup.
                    # Polling sidesteps inotify entirely. It only affects dev-server
                    # hot-reload file watching (no files change during the test), so
                    # the served app and what WebVoyager observes are unchanged.
                    frontend_env["CHOKIDAR_USEPOLLING"] = "true"
                    _fe_pkg = frontend_dir / "package.json"
                    _fe_has_dev = False
                    if _fe_pkg.exists():
                        try:
                            import json as _json
                            _fe_scripts = _json.loads(_fe_pkg.read_text()).get("scripts", {})
                            _fe_has_dev = "dev" in _fe_scripts
                        except Exception:
                            pass
                    if _fe_has_dev:
                        _fe_cmd = ["npm", "run", "dev", "--", "--host", "0.0.0.0",
                                   "--port", str(frontend_runtime_port), "--strictPort"]
                    else:
                        _fe_cmd = ["npm", "start"]
                    frontend_process = subprocess.Popen(
                        _fe_cmd,
                        cwd=str(frontend_dir),
                        env=frontend_env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        preexec_fn=rb.subprocess_setsid,
                    )
                    attempt_info = {"attempt": frontend_attempt, "port": frontend_runtime_port, "status": "starting"}
                    if not rb.wait_for_port(frontend_runtime_port, timeout=60):
                        attempt_info["status"] = "port_not_listening"
                        out, err = b"", b""
                        try:
                            out, err = frontend_process.communicate(timeout=2)
                        except Exception:
                            pass
                        attempt_info["stdout"], attempt_info["stderr"] = _to_text(out), _to_text(err)
                        frontend_attempts.append(attempt_info)
                        rb.kill_port(frontend_runtime_port)
                        try:
                            frontend_process.terminate()
                            frontend_process.wait(timeout=10)
                        except Exception:
                            frontend_process.kill()
                        if frontend_attempt < 2:
                            print(f"[v1-nolog:{project_id}] Frontend attempt {frontend_attempt} failed (port), retrying...")
                            continue
                    elif not rb.wait_for_server(f"http://127.0.0.1:{frontend_runtime_port}", timeout=150):
                        attempt_info["status"] = "http_not_accessible"
                        out, err = b"", b""
                        try:
                            out, err = frontend_process.communicate(timeout=2)
                        except Exception:
                            pass
                        attempt_info["stdout"], attempt_info["stderr"] = _to_text(out), _to_text(err)
                        frontend_attempts.append(attempt_info)
                        rb.kill_port(frontend_runtime_port)
                        try:
                            frontend_process.terminate()
                            frontend_process.wait(timeout=10)
                        except Exception:
                            frontend_process.kill()
                        if frontend_attempt < 2:
                            print(f"[v1-nolog:{project_id}] Frontend attempt {frontend_attempt} failed (HTTP), retrying...")
                            continue
                    else:
                        attempt_info["status"] = "success"
                        frontend_attempts.append(attempt_info)
                        frontend_started = True
                        print(f"[v1-nolog:{project_id}] Frontend started on port {frontend_runtime_port}")
                        break

                if not frontend_started:
                    _write_failure_log(output_dir, {"status": "frontend_not_accessible", "frontend_dir": str(frontend_dir), "attempts": frontend_attempts})
                    result.update(status="failed", webvoyager_status="frontend_not_accessible",
                                  finished_at=datetime.now().isoformat())
                    _write_summary(output_dir, result)
                    return result

            # ----------------------------------------------------------
            # Run WebVoyager (same as run_batch.py:1646-1771).
            # ----------------------------------------------------------
            web_port = frontend_runtime_port if frontend_dir.exists() else backend_runtime_port
            task_file, num_tasks = rb.create_webvoyager_task_file(project_id, port=web_port)
            if not task_file or num_tasks == 0:
                print(f"[v1-nolog:{project_id}] No tasks for project; skipping WebVoyager.")
                result.update(status="completed", webvoyager_status="no_tasks", total_tasks=0,
                              finished_at=datetime.now().isoformat())
                _write_summary(output_dir, result)
                return result

            print(f"[v1-nolog:{project_id}] Running WebVoyager ({num_tasks} tasks) against port {web_port}...")
            _warmup_chromedriver(project_id)
            webvoyager_workers = rb.get_webvoyager_worker_count(num_tasks)
            webvoyager_timeout = webvoyager_timeout_override or max(1800, num_tasks * 360)

            # WebVoyager writes its task dirs directly into output_dir.
            if output_dir.exists():
                # Preserve nothing — clean re-run of this nolog variant.
                for child in list(output_dir.iterdir()):
                    if child.is_dir() and child.name.startswith("task"):
                        shutil.rmtree(child, ignore_errors=True)

            api_key = (os.getenv("WEBVOYAGER_API_KEY") or os.getenv("QWEN_API_KEY") or "").strip()
            api_model = os.getenv("WEBVOYAGER_MODEL", "qwen3.5-plus")
            api_base = os.getenv("WEBVOYAGER_API_BASE_URL") or os.getenv("QWEN_API_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            if not api_key:
                _write_failure_log(output_dir, {"status": "api_key_missing", "message": "WEBVOYAGER_API_KEY or QWEN_API_KEY required"})
                result.update(status="failed", webvoyager_status="api_key_missing",
                              finished_at=datetime.now().isoformat())
                _write_summary(output_dir, result)
                return result

            logp = f"[v1-nolog:{project_id}]"
            print(f"{logp} WebVoyager API: model={api_model}, base={api_base}, workers={webvoyager_workers}")

            # ----------------------------------------------------------
            # Round 0: full run. Then up to MAX_RETRY_ROUNDS rounds that re-run
            # only tasks which broke at the infrastructure level (chrome crash /
            # no output => UNKNOWN), mirroring the watchdog retries the logged-v1
            # experiment used. Genuine NOT_SUCCESS results are kept, not retried.
            # ----------------------------------------------------------
            MAX_RETRY_ROUNDS = 2
            overall_rc = _run_wv_subprocess(task_file, output_dir, webvoyager_workers, max_iter,
                                            api_key, api_model, api_base, webvoyager_timeout, logp, 0)

            def _eval_all() -> None:
                task_result_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("task")]
                for task_dir in task_result_dirs:
                    tid = task_dir.name[len("task"):]
                    result["tasks"][tid] = _task_status(task_dir)

            _eval_all()

            for round_idx in range(1, MAX_RETRY_ROUNDS + 1):
                infra = {tid: st for tid, st in result["tasks"].items()
                         if _is_infra_failure(st, output_dir / f"task{tid}")}
                # Also catch task ids WebVoyager never produced a dir for at all.
                expected_ids = {f"{project_id}--{i + 1}" for i in range(num_tasks)}
                for tid in expected_ids - set(result["tasks"]):
                    infra[tid] = "MISSING_TASK_DIR"
                if not infra:
                    break
                print(f"{logp} Retry round {round_idx}: re-running {len(infra)} infra-failed task(s) "
                      f"(workers=1): {sorted(infra)}")
                retry_file, _ = _write_subset_task_file(project_id, set(infra), web_port)
                if not retry_file:
                    break
                # Clear those task dirs so re-run output is fresh.
                for tid in infra:
                    shutil.rmtree(output_dir / f"task{tid}", ignore_errors=True)
                _run_wv_subprocess(retry_file, output_dir, 1, max_iter, api_key, api_model, api_base,
                                   webvoyager_timeout, logp, round_idx)
                _eval_all()
                try:
                    retry_file.unlink()
                except Exception:
                    pass

            success_count = sum(1 for st in result["tasks"].values() if st == "SUCCESS")
            failed_count = len(result["tasks"]) - success_count
            task_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("task")]
            print(f"{logp} Final eval: {success_count} succeeded, {failed_count} failed, {len(task_dirs)} task_dirs")
            result["webvoyager_status"] = "success" if (success_count > 0 and task_dirs) else (
                "failed" if overall_rc == 0 else "failed"
            )

            result["success_count"] = success_count
            result["failed_count"] = failed_count
            result["total_tasks"] = num_tasks
            result["status"] = "completed"
            result["finished_at"] = datetime.now().isoformat()
            _write_summary(output_dir, result)
            return result
    finally:
        # Cleanup ports + processes.
        try:
            rb.kill_port(frontend_runtime_port)
        except Exception:
            pass
        try:
            rb.kill_port(backend_runtime_port)
        except Exception:
            pass
        for proc in (frontend_process, backend_process):
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


def _write_summary(output_dir: Path, result: dict) -> None:
    (output_dir / "nolog_v1_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WebVoyager on a clean (no-log) v1 source")
    parser.add_argument("--source-dir", required=True, help="Clean v1 source dir, e.g. .../gen_000022/project_000022")
    parser.add_argument("--project-id", required=True, help="Zero-padded project id, e.g. 000022")
    parser.add_argument("--output-dir", required=True, help="Per-project results dir for the nolog WV run")
    parser.add_argument("--max-iter", type=int, default=10, help="WebVoyager max iterations per task")
    parser.add_argument("--webvoyager-timeout", type=int, default=None, help="Override WebVoyager timeout (seconds)")
    args = parser.parse_args()

    # Clear proxy env vars that interfere with API calls (same as run_batch).
    for var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(var, None)

    result = run_clean_v1(
        source_dir=Path(args.source_dir),
        project_id=args.project_id,
        output_dir=Path(args.output_dir),
        max_iter=args.max_iter,
        webvoyager_timeout_override=args.webvoyager_timeout,
    )
    print(f"[v1-nolog:{args.project_id}] DONE status={result['status']} "
          f"wv={result.get('webvoyager_status')} success={result['success_count']}/{result['total_tasks']}")
    # Non-zero exit only on hard failure (so the launcher can surface it).
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
