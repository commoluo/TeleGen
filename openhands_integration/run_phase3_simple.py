#!/usr/bin/env python3
"""Run WebVoyager test on existing v2_experiment projects - simple wrapper."""

import subprocess
import sys
import json
import time
import socket
from pathlib import Path
from datetime import datetime


def kill_port(port):
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


def wait_for_port(port, timeout=60):
    """Wait for port to be in use."""
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(2)
    return False


def main():
    run_dir = Path("batch_runs/run_20260324_205358")
    results = []

    for i in range(1, 6):
        project_id = f"{i:06d}"
        v2_dir = run_dir / f"gen_{project_id}" / f"project_{project_id}_v2_experiment"

        if not v2_dir.exists():
            print(f"Skipping {project_id}: v2_experiment not found")
            continue

        print(f"\n{'='*60}")
        print(f"Testing project {project_id}")
        print(f"{'='*60}")

        # Kill any existing processes on ports
        kill_port(5001)
        kill_port(3000)

        backend_dir = v2_dir / "backend"
        frontend_dir = v2_dir / "frontend"

        backend_process = None
        frontend_process = None

        try:
            # Start backend on port 5001
            if backend_dir.exists():
                backend_cmd = ["npm", "start"]
                backend_process = subprocess.Popen(
                    backend_cmd,
                    cwd=str(backend_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if not wait_for_port(5001, timeout=60):
                    print(f"  Backend failed to start on port 5001")
                    results.append({"project_id": project_id, "status": "backend_failed"})
                    continue
                print(f"  Backend started on port 5001")

            # Start frontend on port 3000
            if frontend_dir.exists():
                frontend_cmd = ["npm", "run", "dev"]
                frontend_process = subprocess.Popen(
                    frontend_cmd,
                    cwd=str(frontend_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                # Give frontend more time to start (vite can take a while)
                if not wait_for_port(3000, timeout=120):
                    print(f"  Frontend failed to start on port 3000")
                    results.append({"project_id": project_id, "status": "frontend_failed"})
                    continue
                print(f"  Frontend started on port 3000")

            # Create WebVoyager task file
            task_file = Path(f"/tmp/webvoyager_task_{project_id}_v2.jsonl")
            web_url = f"http://localhost:3000"

            data_dir = Path("data")
            with open(data_dir / "test.jsonl", "r") as f:
                for line in f:
                    data = json.loads(line.strip())
                    if data.get("id") == project_id:
                        tasks = []
                        for idx, item in enumerate(data.get("ui_instruct", [])):
                            task = {
                                "web_name": f"Generated_Project_{project_id}_v2",
                                "id": f"{project_id}--{idx+1}",
                                "ques": item.get("task", ""),
                                "web": web_url,
                                "expected_result": item.get("expected_result", ""),
                            }
                            tasks.append(task)

                        with open(task_file, "w") as f:
                            for task in tasks:
                                f.write(json.dumps(task) + "\n")
                        print(f"  Created {len(tasks)} tasks for {web_url}")
                        break

            # Run WebVoyager
            wv_output = v2_dir / "webvoyager_v2_results"
            wv_output.mkdir(exist_ok=True)

            api_model = os.getenv("WEBVOYAGER_MODEL", "qwen3.5-plus")
            api_base = os.getenv("WEBVOYAGER_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            api_key = subprocess.run(
                ["python3", "-c", "from dotenv import load_dotenv; load_dotenv(); print(__import__('os').getenv('WEBVOYAGER_API_KEY', '') or __import__('os').getenv('QWEN_API_KEY', ''))"],
                capture_output=True, text=True
            ).stdout.strip()

            if not api_key:
                print(f"  No API key found")
                results.append({"project_id": project_id, "status": "api_key_missing"})
                continue

            cmd = [
                sys.executable, "-m", "webvoyager.run",
                "--test_file", str(task_file),
                "--api_key", api_key,
                "--api_model", api_model,
                "--api_base_url", api_base,
                "--output_dir", str(wv_output),
                "--headless",
                "--num_workers", "1",
                "--max_iter", "5",
            ]

            print(f"  Running WebVoyager...")
            result = subprocess.run(cmd, cwd=Path(".").resolve())

            # Parse results
            success_count = 0
            failed_count = 0
            if wv_output.exists():
                for task_d in wv_output.iterdir():
                    if task_d.is_dir() and task_d.name.startswith("task"):
                        log_file = task_d / "interact_messages.json"
                        if log_file.exists():
                            try:
                                msgs = json.loads(log_file.read_text())
                                if isinstance(msgs, list) and msgs and msgs[-1].get("success"):
                                    success_count += 1
                                else:
                                    failed_count += 1
                            except Exception:
                                failed_count += 1

            status = "success" if failed_count == 0 else ("partial_success" if success_count > 0 else "failed")
            print(f"  WebVoyager: {success_count} succeeded, {failed_count} failed - {status}")

            results.append({
                "project_id": project_id,
                "status": status,
                "success_count": success_count,
                "failed_count": failed_count,
            })

        finally:
            if backend_process:
                backend_process.terminate()
            if frontend_process:
                frontend_process.terminate()
            kill_port(5001)
            kill_port(3000)

    # Save summary
    summary_file = run_dir / f"phase3_v2_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n\nSummary saved to: {summary_file}")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
