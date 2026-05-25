#!/usr/bin/env python3
"""Launch one full pipeline worker container per WebGen project."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional


DEFAULT_IMAGE = "telegen-pipeline:latest"
FORWARDED_ENV = [
    "QWEN_API_KEY",
    "QWEN_API_BASE_URL",
    "QWEN_MODEL",
    "WEBVOYAGER_API_KEY",
    "WEBVOYAGER_API_BASE_URL",
    "WEBVOYAGER_MODEL",
    "WEBVOYAGER_EVAL_API_KEY",
    "WEBVOYAGER_EVAL_API_BASE_URL",
    "WEBVOYAGER_EVAL_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_BASE_URL",
    "DEEPSEEK_MODEL",
    "PIPELINE_MODEL",
    "DEFAULT_MODEL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_EXTRA_BODY",
    "WEBVOYAGER_NUM_WORKERS",
]


@dataclass
class RunningJob:
    project_id: str
    process: subprocess.Popen
    log_file: object
    log_path: Path
    container_name: str
    started_at: float


def _project_range(start: str, end: str) -> List[str]:
    start_i = int(start)
    end_i = int(end)
    if end_i < start_i:
        raise ValueError("--end must be greater than or equal to --start")
    width = max(len(start), len(end), 6)
    return [f"{idx:0{width}d}" for idx in range(start_i, end_i + 1)]


def _parse_projects(value: Optional[str], start: Optional[str], end: Optional[str]) -> List[str]:
    if value:
        projects = [item.strip().zfill(6) for item in value.split(",") if item.strip()]
        if not projects:
            raise ValueError("--projects did not contain any project ids")
        return projects
    if start and end:
        return _project_range(start.zfill(6), end.zfill(6))
    raise ValueError("Provide either --projects or both --start and --end")


def _existing_env_files(workspace: Path, explicit: Iterable[str]) -> List[Path]:
    candidates = [workspace / ".env"]
    candidates.extend(Path(item).expanduser().resolve() for item in explicit)

    result: List[Path] = []
    seen = set()
    for path in candidates:
        if path.exists() and path.is_file() and path not in seen:
            result.append(path)
            seen.add(path)
    return result


def _run_checked(cmd: List[str], cwd: Path) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _build_image(workspace: Path, image: str, openhands_pip_spec: Optional[str], container_cli: str) -> None:
    cmd = [
        container_cli,
        "build",
        "-f",
        str(workspace / "docker" / "pipeline.Dockerfile"),
        "-t",
        image,
    ]
    if openhands_pip_spec:
        cmd.extend(["--build-arg", f"OPENHANDS_PIP_SPEC={openhands_pip_spec}"])
    cmd.append(str(workspace))
    _run_checked(cmd, cwd=workspace)


def _launch_job(
    project_id: str,
    args: argparse.Namespace,
    workspace: Path,
    run_root: Path,
    env_files: List[Path],
    logs_dir: Path,
) -> RunningJob:
    project_run_dir = run_root / f"project_{project_id}"
    project_run_dir.mkdir(parents=True, exist_ok=True)

    container_name = f"telegen-{project_id}-{int(time.time())}"
    worker_home = f"/tmp/telegen-home-{project_id}"

    cmd = [
        args.container_cli,
        "run",
        "--rm",
        "--name",
        container_name,
        "--workdir",
        str(workspace),
        "--volume",
        f"{workspace}:{workspace}",
    ]

    if args.mount_docker_sock:
        docker_sock = Path("/var/run/docker.sock")
        if docker_sock.exists():
            cmd.extend(["--volume", "/var/run/docker.sock:/var/run/docker.sock"])
        else:
            raise FileNotFoundError("/var/run/docker.sock not found; use --no-mount-docker-sock if OpenHands does not need Docker")

    for env_file in env_files:
        cmd.extend(["--env-file", str(env_file)])

    for name in FORWARDED_ENV:
        if name in os.environ:
            cmd.extend(["--env", name])

    cmd.extend(
        [
            "--env",
            f"TELEGEN_WORKER_HOME={worker_home}",
            "--env",
            f"WEBVOYAGER_NUM_WORKERS={args.webvoyager_workers}",
            "--env",
            f"PIPELINE_WEB_STACK_LOCK=/tmp/telegen_web_stack_{project_id}.lock",
        ]
    )

    if args.raw_logs:
        cmd.extend(["--env", "RAW_LOGS_MODE=true"])
    if args.only_repair:
        cmd.extend(["--env", "ONLY_REPAIR_MODE=true"])

    if args.extra_docker_arg:
        for extra_arg in args.extra_docker_arg:
            cmd.extend(extra_arg.split())

    worker_cmd = [
        args.image,
        "bash",
        args.worker_script,
        "--project-id",
        project_id,
        "--workspace",
        str(workspace),
        "--run-dir",
        str(project_run_dir),
    ]
    if args.model:
        worker_cmd.extend(["--model", args.model])
    if args.reuse_openhands_workspace:
        worker_cmd.append("--reuse-openhands-workspace")

    cmd.extend(worker_cmd)

    log_path = logs_dir / f"project_{project_id}.log"
    log_file = log_path.open("w", encoding="utf-8")
    log_file.write("+ " + " ".join(cmd) + "\n")
    log_file.flush()

    process = subprocess.Popen(
        cmd,
        cwd=str(workspace),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return RunningJob(
        project_id=project_id,
        process=process,
        log_file=log_file,
        log_path=log_path,
        container_name=container_name,
        started_at=time.time(),
    )


def _write_summary(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run project-level full pipeline workers in Docker")
    parser.add_argument("--workspace", default=str(Path.cwd()), help="Repository path on the host")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Worker Docker image")
    parser.add_argument("--container-cli", default=os.environ.get("CONTAINER_CLI", "docker"), help="Container CLI to use, e.g. docker or podman")
    parser.add_argument("--build", action="store_true", help="Build the worker image before launching")
    parser.add_argument("--openhands-pip-spec", default=None, help="Override Docker build arg OPENHANDS_PIP_SPEC")
    parser.add_argument("--projects", help="Comma-separated project ids, e.g. 000001,000002")
    parser.add_argument("--start", help="Start project id, e.g. 000001")
    parser.add_argument("--end", help="End project id, e.g. 000010")
    parser.add_argument("--workers", type=int, default=2, help="Max project containers running at once")
    parser.add_argument("--run-root", default=None, help="Output root; defaults to batch_runs/multi_docker_run_<timestamp>")
    parser.add_argument("--model", default=None, help="Unified model passed through to the existing pipeline")
    parser.add_argument("--raw-logs", action="store_true", help="Raw-logs ablation: skip LLM brief, use raw telemetry_report.md for repair")
    parser.add_argument("--only-repair", action="store_true", help="Only-repair mode: skip v1 generation + injection + WV1, only run repair + WV2")
    parser.add_argument("--skip-existing", action="store_true", help="Skip projects that already have dynamic_repair_logged_summary.json or baseline_dual_repair_summary.json")
    parser.add_argument("--webvoyager-workers", type=int, default=2, help="WebVoyager workers inside each project container")
    parser.add_argument("--env-file", action="append", default=[], help="Extra docker --env-file path; can be repeated")
    parser.add_argument("--no-mount-docker-sock", dest="mount_docker_sock", action="store_false", help="Do not mount /var/run/docker.sock")
    parser.set_defaults(mount_docker_sock=True)
    parser.add_argument("--reuse-openhands-workspace", action="store_true", help="Use symlink reuse instead of copying generated projects")
    parser.add_argument("--extra-docker-arg", action="append", default=[], help="Extra docker run argument string; can be repeated")
    parser.add_argument("--worker-script", default="openhands_integration/run_project_worker.sh", help="Worker entrypoint script inside the container")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    if not (workspace / "openhands_integration" / "run_full_pipeline_llm_injection.sh").exists():
        print(f"ERROR: workspace does not look like TeleGen: {workspace}", file=sys.stderr)
        return 2

    projects = _parse_projects(args.projects, args.start, args.end)
    if args.workers < 1:
        print("ERROR: --workers must be >= 1", file=sys.stderr)
        return 2

    if args.build:
        _build_image(workspace, args.image, args.openhands_pip_spec, args.container_cli)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.run_root).expanduser().resolve() if args.run_root else workspace / "batch_runs" / f"multi_docker_run_{timestamp}"
    logs_dir = run_root / "launcher_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    env_files = _existing_env_files(workspace, args.env_file)
    print(f"Projects: {', '.join(projects)}")
    print(f"Workers: {args.workers}")
    print(f"Run root: {run_root}")
    print(f"Image: {args.image}")
    print(f"Container CLI: {args.container_cli}")
    if args.raw_logs:
        print("Raw-logs mode: ON (no LLM brief)")
    if args.only_repair:
        print("Only-repair mode: ON (skip Phase 1 + Phase 2B)")
    print("Env files: " + (", ".join(str(path) for path in env_files) if env_files else "none"))

    summary = {
        "run_root": str(run_root),
        "started_at": datetime.now().isoformat(),
        "image": args.image,
        "container_cli": args.container_cli,
        "raw_logs_mode": args.raw_logs,
        "only_repair_mode": args.only_repair,
        "workers": args.workers,
        "projects": [],
    }
    summary_path = run_root / "multi_docker_summary.json"
    _write_summary(summary_path, summary)

    pending = list(projects)
    if args.skip_existing:
        skipped = 0
        filtered = []
        for pid in pending:
            prd = run_root / f"project_{pid}"
            if (prd / "dynamic_repair_logged_summary.json").exists() or (prd / "baseline_dual_repair_summary.json").exists():
                skipped += 1
                continue
            filtered.append(pid)
        if skipped:
            print(f"Skipped {skipped} already-completed projects")
        pending = filtered
        # Also load existing completed from summary to preserve them
        if summary_path.exists():
            try:
                old = json.loads(summary_path.read_text())
                for item in old.get("projects", []):
                    if item.get("project_id") not in {r["project_id"] for r in summary["projects"]}:
                        summary["projects"].append(item)
            except Exception:
                pass
    running: List[RunningJob] = []
    completed = []

    while pending or running:
        while pending and len(running) < args.workers:
            project_id = pending.pop(0)
            job = _launch_job(project_id, args, workspace, run_root, env_files, logs_dir)
            running.append(job)
            print(f"[{project_id}] launched container={job.container_name} log={job.log_path}", flush=True)

        time.sleep(1)

        still_running: List[RunningJob] = []
        for job in running:
            returncode = job.process.poll()
            if returncode is None:
                still_running.append(job)
                continue

            job.log_file.close()
            elapsed = round(time.time() - job.started_at, 1)
            record = {
                "project_id": job.project_id,
                "container_name": job.container_name,
                "returncode": returncode,
                "elapsed_seconds": elapsed,
                "log": str(job.log_path),
                "run_dir": str(run_root / f"project_{job.project_id}"),
            }
            completed.append(record)
            summary["projects"] = completed
            _write_summary(summary_path, summary)
            status = "ok" if returncode == 0 else f"failed({returncode})"
            print(f"[{job.project_id}] {status} elapsed={elapsed}s", flush=True)

        running = still_running

    summary["finished_at"] = datetime.now().isoformat()
    summary["failed"] = [item for item in completed if item["returncode"] != 0]
    _write_summary(summary_path, summary)
    print(f"Summary: {summary_path}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())