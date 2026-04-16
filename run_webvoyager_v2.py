#!/usr/bin/env python3
"""
Simple WebVoyager testing for v2_experiment projects.

Usage:
    python3 run_webvoyager_v2.py --project 000001
"""

import argparse
import json
import subprocess
import sys
import time
import socket
import os
from pathlib import Path


def kill_port(port):
    """Kill process using port."""
    try:
        result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        if result.stdout.strip():
            for pid in result.stdout.strip().split("\n"):
                try:
                    os.kill(int(pid), 9)
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


def wait_for_server(url, timeout=60):
    """Wait for server to be accessible via curl."""
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip() == "200":
            return True
        time.sleep(2)
    return False


def create_task_file(project_id, port=3000):
    """Create WebVoyager task file."""
    task_file = Path(f"/tmp/webv_task_{project_id}.jsonl")
    data_dir = Path("data")

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
                        "web": f"http://localhost:{port}",
                        "expected_result": item.get("expected_result", ""),
                    }
                    tasks.append(task)

                with open(task_file, "w") as f:
                    for task in tasks:
                        f.write(json.dumps(task) + "\n")
                return task_file, len(tasks)
    return None, 0


def main():
    parser = argparse.ArgumentParser(description="Run WebVoyager on v2_experiment project")
    parser.add_argument("--project", required=True, help="Project ID (e.g., 000001)")
    parser.add_argument("--experiment-dir", help="Path to v2_experiment directory")
    parser.add_argument("--run-dir", default="batch_runs/run_20260324_205358", help="Batch run directory")
    parser.add_argument("--port", type=int, default=3000, help="Frontend port")
    parser.add_argument("--backend-port", type=int, default=5001, help="Backend port")
    parser.add_argument("--timeout", type=int, default=1800, help="WebVoyager timeout")
    args = parser.parse_args()

    # Determine experiment directory
    if args.experiment_dir:
        exp_dir = Path(args.experiment_dir)
    else:
        exp_dir = Path(args.run_dir) / f"gen_{args.project}" / f"project_{args.project}_v2_experiment"

    if not exp_dir.exists():
        print(f"Error: Experiment directory not found: {exp_dir}")
        sys.exit(1)

    print(f"Testing project {args.project}")
    print(f"Experiment directory: {exp_dir}")

    # Kill existing processes
    kill_port(args.port)
    kill_port(args.backend_port)
    time.sleep(2)

    backend_dir = exp_dir / "backend"
    frontend_dir = exp_dir / "frontend"

    # Start backend
    if backend_dir.exists():
        print(f"Starting backend on port {args.backend_port}...")
        proc = subprocess.Popen(
            ["npm", "start"],
            cwd=str(backend_dir),
            stdout=open(f"/tmp/backend_{args.project}.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if not wait_for_port(args.backend_port, timeout=60):
            print("Error: Backend failed to start")
            sys.exit(1)
        print(f"Backend started on port {args.backend_port}")

    # Start frontend
    if frontend_dir.exists():
        print(f"Starting frontend on port {args.port}...")
        subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(frontend_dir),
            stdout=open(f"/tmp/frontend_{args.project}.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        # Wait for vite to compile and start
        time.sleep(5)
        if not wait_for_server(f"http://localhost:{args.port}", timeout=120):
            print("Error: Frontend failed to start")
            sys.exit(1)
        print(f"Frontend started on port {args.port}")

    try:
        # Create task file
        task_file, num_tasks = create_task_file(args.project, port=args.port)
        if not task_file or num_tasks == 0:
            print(f"Error: No tasks found for project {args.project}")
            sys.exit(1)
        print(f"Created {num_tasks} tasks -> {task_file}")

        # Get API key
        api_key = subprocess.run(
            ["python3", "-c", "from dotenv import load_dotenv; load_dotenv(); print(__import__('os').getenv('MINIMAX_API_KEY', ''))"],
            capture_output=True, text=True
        ).stdout.strip()

        if not api_key:
            print("Error: MINIMAX_API_KEY not found")
            sys.exit(1)

        # Output directory
        output_dir = exp_dir / "webvoyager_v2_results"
        output_dir.mkdir(exist_ok=True)

        # Run WebVoyager
        print(f"Running WebVoyager...")
        webvoyager_dir = Path("webvoyager")
        cmd = [
            sys.executable, "run.py",
            "--test_file", str(task_file),
            "--api_key", api_key,
            "--api_model", "MiniMax-M2.7-highspeed",
            "--api_base_url", "https://api.minimaxi.com/v1",
            "--output_dir", str(output_dir),
            "--headless",
            "--num_workers", "1",
            "--max_iter", "5",
        ]

        result = subprocess.run(cmd, cwd=webvoyager_dir)

        # Parse results
        success_count = 0
        failed_count = 0
        if output_dir.exists():
            for task_d in output_dir.iterdir():
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
        print(f"\n{'='*50}")
        print(f"Result: {status}")
        print(f"Success: {success_count}, Failed: {failed_count}")
        print(f"Results saved to: {output_dir}")
        print(f"{'='*50}")

    finally:
        kill_port(args.port)
        kill_port(args.backend_port)


if __name__ == "__main__":
    main()
