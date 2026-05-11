#!/usr/bin/env python3
"""Watch and auto-restart the per-project serial pipeline.

The watchdog monitors one serial pipeline log plus the current launcher PID.
If the process dies unexpectedly or known hard-failure patterns appear in the log,
it cleans up child processes/ports and restarts from the current project.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


PROJECT_PHASE1_RE = re.compile(r"=== \[(\d{6})\] Phase 1:")
PROJECT_PHASE2_RE = re.compile(r"=== \[(\d{6})\] Phase 2:")
RUN_DIR_RE = re.compile(r"Batch output:\s*(.+/batch_runs/run_\d{8}_\d{6})")
PHASE1_DONE_RE = re.compile(r"\[(\d{6})\] Phase 1 complete\. Run dir:\s*(.+/batch_runs/run_\d{8}_\d{6})")
PHASE2_DONE_RE = re.compile(r"\[(\d{6})\] Phase 2 complete")
REPORT_RE = re.compile(r"\[(\d{6})\] Analysis report:\s*(.+)")

FAILURE_PATTERNS = [
    re.compile(r"Generation:\s+FAILED"),
    re.compile(r"TIMEOUT during processing"),
    re.compile(r"WebVoyager:\s+PROCESS FAILED"),
    re.compile(r"FAILED \(cannot access website detected in task logs\)"),
    re.compile(r"Frontend failed to start"),
    re.compile(r"Backend failed to start"),
    re.compile(r"backend_failed_to_start"),
    re.compile(r"frontend_failed_to_start"),
    re.compile(r"api_key_missing"),
    re.compile(r"LLM failed for "),
    re.compile(r"Invalid patch for "),
    re.compile(r"Patch apply failed for "),
    re.compile(r"Patch validation failed for "),
    re.compile(r"ERROR:\s"),
]

SUCCESS_SENTINEL = "Pipeline (LLM Injection) complete"


@dataclass
class WatchState:
    current_project: Optional[str] = None
    current_run_dir: Optional[Path] = None
    last_phase: Optional[str] = None
    last_restart_project: Optional[str] = None
    restarts_by_project: Dict[str, int] = field(default_factory=dict)
    file_offset: int = 0
    last_log_activity_ts: float = field(default_factory=time.time)


class SerialPipelineWatchdog:
    def __init__(
        self,
        workspace: Path,
        log_path: Path,
        main_pid: int,
        start_id: str,
        end_id: str,
        model: str,
        no_reuse_workspace: bool,
        watchdog_log: Path,
        poll_seconds: float = 30.0,
        max_restarts_per_project: int = 2,
        stall_seconds: float = 1800.0,
    ) -> None:
        self.workspace = workspace
        self.log_path = log_path
        self.main_pid = main_pid
        self.start_id = start_id
        self.end_id = end_id
        self.model = model
        self.no_reuse_workspace = no_reuse_workspace
        self.watchdog_log = watchdog_log
        self.poll_seconds = poll_seconds
        self.max_restarts_per_project = max_restarts_per_project
        self.stall_seconds = stall_seconds
        self.state = WatchState()

    def log(self, message: str) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        line = f"[{stamp}] {message}"
        print(line, flush=True)
        with self.watchdog_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def read_new_log_text(self) -> str:
        if not self.log_path.exists():
            return ""
        with self.log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(self.state.file_offset)
            text = handle.read()
            self.state.file_offset = handle.tell()
        if text:
            self.state.last_log_activity_ts = time.time()
        return text

    def scan_log_text(self, text: str) -> Optional[str]:
        failure_reason = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            match = PROJECT_PHASE1_RE.search(line)
            if match:
                self.state.current_project = match.group(1)
                self.state.last_phase = "phase1"

            match = PROJECT_PHASE2_RE.search(line)
            if match:
                self.state.current_project = match.group(1)
                self.state.last_phase = "phase2"

            match = RUN_DIR_RE.search(line)
            if match:
                self.state.current_run_dir = Path(match.group(1).strip())

            match = PHASE1_DONE_RE.search(line)
            if match:
                self.state.current_project = match.group(1)
                self.state.current_run_dir = Path(match.group(2).strip())
                self.state.last_phase = "phase1_done"
                self.inspect_phase1_outputs(match.group(1), self.state.current_run_dir)

            match = PHASE2_DONE_RE.search(line)
            if match:
                self.state.current_project = match.group(1)
                self.state.last_phase = "phase2_done"
                if self.state.current_run_dir:
                    self.inspect_phase2_outputs(match.group(1), self.state.current_run_dir)

            match = REPORT_RE.search(line)
            if match:
                project_id = match.group(1)
                report_path = Path(match.group(2).strip())
                self.state.current_project = project_id
                self.state.last_phase = "report_done"
                if report_path.exists():
                    self.log(f"Project {project_id}: analysis report written to {report_path}")
                else:
                    failure_reason = f"Report missing for {project_id}: {report_path}"

            for pattern in FAILURE_PATTERNS:
                if pattern.search(line):
                    failure_reason = line

        return failure_reason

    def inspect_phase1_outputs(self, project_id: str, run_dir: Path) -> None:
        gen_report = run_dir / f"gen_{project_id}" / "generation_report.json"
        inject_report = run_dir / f"gen_{project_id}" / "log_injection_report.json"
        wv_dir = run_dir / "webvoyager_results" / project_id
        batch_results = run_dir / "batch_results.json"

        if not gen_report.exists():
            self.log(f"Project {project_id}: generation_report.json missing")
            return
        if not inject_report.exists():
            self.log(f"Project {project_id}: log_injection_report.json missing")
            return

        gen_obj = json.loads(gen_report.read_text(encoding="utf-8"))
        inject_obj = json.loads(inject_report.read_text(encoding="utf-8"))

        webvoyager_status = None
        if batch_results.exists():
            try:
                batch_obj = json.loads(batch_results.read_text(encoding="utf-8"))
                for item in batch_obj.get("projects", []):
                    if str(item.get("project_id")) == project_id:
                        webvoyager_status = item.get("webvoyager_status")
                        break
            except Exception as exc:  # noqa: BLE001
                self.log(f"Project {project_id}: failed to parse batch_results.json: {exc}")

        if not wv_dir.exists():
            self.log(
                f"Project {project_id}: phase1 artifacts present but webvoyager_results missing; "
                f"generation={gen_obj.get('status')}, injection={inject_obj.get('status')}, "
                f"webvoyager_status={webvoyager_status}"
            )
            return

        task_dirs = [p for p in wv_dir.iterdir() if p.is_dir() and p.name.startswith("task")]

        self.log(
            f"Project {project_id}: phase1 artifacts ok; generation={gen_obj.get('status')}, "
            f"injection={inject_obj.get('status')}, webvoyager_status={webvoyager_status}, wv_tasks={len(task_dirs)}"
        )

    def inspect_phase2_outputs(self, project_id: str, run_dir: Path) -> None:
        summary_file = run_dir / "dynamic_repair_batch_summary.json"
        if not summary_file.exists():
            self.log(f"Project {project_id}: dynamic_repair_batch_summary.json missing")
            return

        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        project_items = [item for item in summary.get("projects", []) if item.get("project_id") == project_id]
        if not project_items:
            self.log(f"Project {project_id}: no optimize summary entry yet")
            return

        item = project_items[-1]
        phase3 = item.get("phase3") or {}
        self.log(
            f"Project {project_id}: phase2 artifacts ok; optimize={item.get('status')}, "
            f"phase3={phase3.get('status')}, success_count={phase3.get('success_count', 0)}"
        )

    def kill_tree(self, pid: int) -> None:
        try:
            child_output = subprocess.check_output(["pgrep", "-P", str(pid)], text=True)
            child_pids = [int(part.strip()) for part in child_output.splitlines() if part.strip()]
        except subprocess.CalledProcessError:
            child_pids = []

        for child_pid in child_pids:
            self.kill_tree(child_pid)

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as exc:  # noqa: BLE001
            self.log(f"Failed to SIGTERM pid={pid}: {exc}")

    def cleanup_ports(self) -> None:
        for port in (3000, 5001):
            try:
                result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True, check=False)
                for raw_pid in result.stdout.splitlines():
                    raw_pid = raw_pid.strip()
                    if not raw_pid:
                        continue
                    try:
                        os.kill(int(raw_pid), signal.SIGTERM)
                        self.log(f"Killed pid={raw_pid} on port {port}")
                    except ProcessLookupError:
                        pass
            except Exception as exc:  # noqa: BLE001
                self.log(f"Port cleanup failed for {port}: {exc}")

    def restart_from_current_project(self, reason: str) -> None:
        project_id = self.state.current_project or self.start_id
        retries = self.state.restarts_by_project.get(project_id, 0)
        if retries >= self.max_restarts_per_project:
            self.log(f"Project {project_id}: hit max restarts ({self.max_restarts_per_project}); watchdog stops retrying. Last reason: {reason}")
            raise SystemExit(1)

        self.state.restarts_by_project[project_id] = retries + 1
        self.state.last_restart_project = project_id
        self.log(f"Restarting from project {project_id}; attempt {retries + 1}/{self.max_restarts_per_project}. Reason: {reason}")

        if self.process_alive(self.main_pid):
            self.kill_tree(self.main_pid)
            time.sleep(2)

        self.cleanup_ports()
        time.sleep(2)

        cmd = [
            "bash",
            "openhands_integration/run_full_pipeline_llm_injection.sh",
            "--start",
            project_id,
            "--end",
            self.end_id,
            "--model",
            self.model,
        ]
        if self.state.current_run_dir:
            cmd.extend(["--run-dir", str(self.state.current_run_dir)])
        if self.no_reuse_workspace:
            cmd.append("--no-reuse-openhands-workspace")

        with self.log_path.open("a", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(  # noqa: S603
                cmd,
                cwd=str(self.workspace),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONUNBUFFERED="1"),
            )

        self.main_pid = proc.pid
        self.log(f"Restarted serial pipeline with pid={self.main_pid} from project {project_id}")

    def initialize_state_from_existing_log(self) -> None:
        if not self.log_path.exists():
            return
        text = self.log_path.read_text(encoding="utf-8", errors="ignore")
        self.state.file_offset = len(text)
        if text:
            self.state.last_log_activity_ts = time.time()
        failure = self.scan_log_text(text)
        if failure:
            self.log(f"Existing log already contains failure marker: {failure}")

    def run(self) -> None:
        self.initialize_state_from_existing_log()
        self.log(
            f"Watchdog attached: pid={self.main_pid}, current_project={self.state.current_project}, "
            f"run_dir={self.state.current_run_dir}"
        )

        while True:
            new_text = self.read_new_log_text()
            failure_reason = self.scan_log_text(new_text) if new_text else None

            if failure_reason:
                self.restart_from_current_project(failure_reason)

            if not self.process_alive(self.main_pid):
                tail = ""
                if self.log_path.exists():
                    tail = self.log_path.read_text(encoding="utf-8", errors="ignore")[-4000:]
                if SUCCESS_SENTINEL in tail:
                    self.log("Serial pipeline finished successfully; watchdog exiting.")
                    return
                self.restart_from_current_project("main pipeline process exited unexpectedly")

            idle_seconds = time.time() - self.state.last_log_activity_ts
            if idle_seconds >= self.stall_seconds:
                self.restart_from_current_project(f"no log progress for {int(idle_seconds)} seconds")

            time.sleep(self.poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch and auto-restart the serial pipeline")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--main-pid", required=True, type=int)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--watchdog-log", required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-restarts-per-project", type=int, default=2)
    parser.add_argument("--stall-seconds", type=float, default=1800.0)
    parser.add_argument("--no-reuse-openhands-workspace", action="store_true")
    args = parser.parse_args()

    watchdog = SerialPipelineWatchdog(
        workspace=Path(args.workspace).resolve(),
        log_path=Path(args.log).resolve(),
        main_pid=args.main_pid,
        start_id=args.start,
        end_id=args.end,
        model=args.model,
        no_reuse_workspace=args.no_reuse_openhands_workspace,
        watchdog_log=Path(args.watchdog_log).resolve(),
        poll_seconds=args.poll_seconds,
        max_restarts_per_project=args.max_restarts_per_project,
        stall_seconds=args.stall_seconds,
    )
    watchdog.run()


if __name__ == "__main__":
    main()