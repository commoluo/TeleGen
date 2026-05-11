"""
OpenHands Generation with Semantic Logging Pipeline
================================================

Two-step process:
1. Generate fullstack code with OpenHands (without logs)
2. Inject semantic logs using dedicated LLM log injector (fast)

Each execution creates an isolated folder:
openhands_runs/run_YYYYMMDD_HHMMSS_project_XXXXXX/
├── task.txt                    # Original task
├── generation_report.json       # Generation result
├── project_XXXXXX/            # Generated project
│   ├── backend/
│   └── frontend/
└── log_injection_report.json  # Log injection result

Usage:
    python openhands_with_logging.py --single 000001
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file
env_path = Path(__file__).parent.parent / "alternative_generation" / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Import the fast LLM log injector (NOT OpenHands)
from openhands_integration.llm_log_injector import SemanticLogInjector

# ============================================================================
# Configuration
# ============================================================================

OPENHANDS_CONFIG = {
    "workspace_dir": "./openhands_workspace",
    "timeout": 1800,
}


# ============================================================================
# OpenHands Code Generator
# ============================================================================

class OpenHandsCodeGenerator:
    """Generate fullstack code without logs"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = {**OPENHANDS_CONFIG, **(config or {})}
        self.workspace = Path(self.config.get("workspace_dir", "./openhands_workspace"))
        self.workspace.mkdir(parents=True, exist_ok=True)

    def generate_from_instruction(
        self,
        project_id: str,
        instruction: str,
        category: Dict,
        ui_instruct: List[Dict],
        output_dir: Path,
    ) -> Dict[str, Any]:
        task = self._build_generation_task(
            project_id, instruction, category, ui_instruct
        )

        task_id = f"gen_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        task_workspace = self.workspace / task_id
        task_workspace.mkdir(parents=True, exist_ok=True)

        task_file = task_workspace / "task.txt"
        task_file.write_text(task)

        result = self._run_openhands(task_file, task_workspace)
        output_path = self._find_and_copy_project(task_workspace, output_dir, project_id)

        return {
            "project_id": project_id,
            "task_id": task_id,
            "task_file": str(task_file),
            "status": "completed" if result["returncode"] == 0 else "failed",
            "returncode": result["returncode"],
            "output_path": str(output_path) if output_path else None,
            "stdout": result.get("stdout", "")[:3000],
        }

    def _build_generation_task(
        self,
        project_id: str,
        instruction: str,
        category: Dict,
        ui_instruct: List[Dict],
    ) -> str:
        ui_requirements = self._extract_ui_requirements(ui_instruct)

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
{ui_requirements}

## Technical Requirements:
Generate a fullstack application with:

1. **Backend (Node.js/Express)**:
   - RESTful API endpoints
   - Proper error handling with JSON response format: {{"success": true/false, "data": ..., "error": ...}}
   - Input validation
   - CORS enabled
   - Port: 5001

2. **Frontend (React)**:
   - Responsive UI design
   - State management
   - API integration with backend
   - Build tool: Vite
   - Port: 3000

3. **Project Structure**:
```
project_{project_id}/
├── backend/
│   ├── app.js
│   ├── routes/
│   ├── controllers/
│   ├── data/
│   ├── middleware/
│   └── package.json
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.js
```

## Design Requirements:
- Background color: {self._extract_color(instruction, 'background')}
- Component color: {self._extract_color(instruction, 'component')}

## Implementation Steps:
1. Create project directory structure
2. Generate backend code with Express (NO logging statements)
3. Generate frontend code with React + Vite (NO logging statements)
4. Create package.json files with all dependencies
5. Verify code has no syntax errors

## Important:
- Generate COMPLETE, WORKING code. No placeholders, TODOs.
- NO console.log, NO logger.info, NO debug statements
- All files must be syntactically correct.
"""

    def _extract_ui_requirements(self, ui_instruct: List[Dict]) -> str:
        if not ui_instruct:
            return "Standard web application interface"
        requirements = []
        for item in ui_instruct[:3]:
            task = item.get('task', '')
            expected = item.get('expected_result', '')
            if task:
                requirements.append(f"- Task: {task}")
            if expected:
                requirements.append(f"  Expected: {expected}")
        return "\n".join(requirements) if requirements else "Standard web application"

    def _extract_color(self, instruction: str, color_type: str) -> str:
        import re
        patterns = [
            rf'{color_type}.*?color.*?(\w+)',
            rf'{color_type}:\s*(\w+)',
            rf'set the {color_type}.*?to\s+(\w+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, instruction, re.IGNORECASE)
            if match:
                return match.group(1)
        return "white" if color_type == "background" else "navy"

    def _run_openhands(self, task_file: Path, workspace: Path) -> Dict[str, Any]:
        cmd = [
            "openhands",
            "--headless",
            "--always-approve",
            "--override-with-envs",
            "-f", str(task_file.resolve()),
        ]

        env = dict(os.environ)
        qwen_key = env.get("QWEN_API_KEY") or env.get("WEBVOYAGER_API_KEY")
        if qwen_key:
            env["LLM_API_KEY"] = qwen_key
            qwen_model = os.getenv("QWEN_MODEL", "qwen3.5-plus")
            env["LLM_MODEL"] = f"openai/{qwen_model}"
            env["LLM_PROVIDER"] = "openai"
            env["LLM_BASE_URL"] = os.getenv("QWEN_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        env["TTY_INTERACTIVE"] = "1"

        try:
            result = subprocess.run(
                cmd,
                cwd=str(workspace.resolve()),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.config.get("timeout", 1800),
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "timeout"}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    def _find_and_copy_project(self, task_workspace: Path, output_dir: Path, project_id: str) -> Optional[Path]:
        """Find and copy the generated project to output directory."""
        output_path = output_dir / f"project_{project_id}"

        # Define possible source locations
        possible_sources = [
            task_workspace / "workspace" / f"project_{project_id}",
            task_workspace / "workspace",
            task_workspace / f"project_{project_id}",
            task_workspace,
        ]

        src_dir = None
        for src in possible_sources:
            if src.exists():
                # Check if this directory has a backend folder
                if (src / "backend").exists():
                    src_dir = src
                    break
                # For task_workspace, check if it itself has backend
                if src == task_workspace and (src / "backend").exists():
                    src_dir = src
                    break

        if not src_dir:
            print(f"    WARNING: Could not find project source in {task_workspace}")
            return None

        # Remove existing output if present
        if output_path.exists():
            shutil.rmtree(output_path)

        # Copy the entire directory
        try:
            shutil.copytree(src_dir, output_path)
            print(f"    Copied project from {src_dir.relative_to(task_workspace)}")

            # Verify backend files exist
            backend_controller = output_path / "backend" / "controllers"
            if not backend_controller.exists():
                print(f"    WARNING: controllers folder missing")
            else:
                controllers = list(backend_controller.glob("*.js"))
                print(f"    Found {len(controllers)} controller files")

            return output_path

        except Exception as e:
            print(f"    ERROR copying project: {e}")
            return None


class AstLogInjector:
    """Run the AST injector script against a generated project."""

    def __init__(self):
        self.script_path = Path(__file__).parent / "ast_injector.js"

    def inject_to_project(self, project_path: str) -> Dict[str, Any]:
        project = Path(project_path)
        if not project.exists():
            return {"status": "error", "message": "Project not found"}

        cmd = ["node", str(self.script_path.resolve()), str(project.resolve())]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(project.parent.resolve()),
            )
            return {
                "status": "completed" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "message": "AST injector timed out"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


def build_task_context(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "project_id": entry.get("id", ""),
        "instruction": entry.get("instruction", ""),
        "category": entry.get("Category", {}),
        "ui_instruct": entry.get("ui_instruct", []),
    }


def copy_project_variant(source_dir: Path, target_dir: Path) -> Path:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def run_selected_injector(
    logging_mode: str,
    project_dir: Path,
    task_context: Dict[str, Any],
) -> Dict[str, Any]:
    if logging_mode == "ast":
        injector = AstLogInjector()
        return injector.inject_to_project(str(project_dir))

    injector = SemanticLogInjector()
    return injector.inject_to_project(
        str(project_dir),
        task_context=task_context,
        project_id=task_context.get("project_id"),
        test_spec_file="data/test.jsonl",
    )


def run_injection_comparison(
    project_dir: Path,
    project_id: str,
    task_context: Dict[str, Any],
    run_dir: Path,
) -> Dict[str, Any]:
    ast_dir = copy_project_variant(project_dir, run_dir / f"project_{project_id}_ast")
    llm_dir = copy_project_variant(project_dir, run_dir / f"project_{project_id}_llm")

    ast_result = run_selected_injector("ast", ast_dir, task_context)
    llm_result = run_selected_injector("llm", llm_dir, task_context)

    comparison = {
        "project_id": project_id,
        "mode": "compare",
        "baseline_project": str(project_dir),
        "ast_project": str(ast_dir),
        "llm_project": str(llm_dir),
        "ast": ast_result,
        "llm": llm_result,
        "timestamp": datetime.now().isoformat(),
    }

    with open(run_dir / "compare_log_injection_report.json", "w") as handle:
        json.dump(comparison, handle, indent=2)

    return comparison


# ============================================================================
# Main Pipeline
# ============================================================================

def run_pipeline(
    input_file: str = "data/test.jsonl",
    base_output_dir: str = "openhands_runs",
    start_id: Optional[str] = None,
    end_id: Optional[str] = None,
    logging_mode: str = "llm",
):
    """
    Run pipeline with organized output structure.

    Output structure:
    openhands_runs/
    └── run_YYYYMMDD_HHMMSS_project_XXXXXX/
        ├── task.txt                    # Original task sent to OpenHands
        ├── generation_report.json      # Generation result
        ├── project_XXXXXX/            # Generated project
        │   ├── backend/
        │   └── frontend/
        └── log_injection_report.json  # Log injection result
    """
    input_path = Path(input_file)
    base_output_path = Path(base_output_dir)
    base_output_path.mkdir(parents=True, exist_ok=True)

    generator = OpenHandsCodeGenerator()
    results = []
    processed = 0
    failed = 0

    print(f"Reading from: {input_path}")
    print(f"Base output directory: {base_output_path}")

    with open(input_path, 'r') as f:
        lines = f.readlines()

    for line in lines:
        entry = json.loads(line.strip())
        project_id = entry.get('id', '')

        if start_id and project_id < start_id:
            continue
        if end_id and project_id > end_id:
            break

        # Create unique run directory for this execution
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{project_id}"
        run_dir = base_output_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"Processing project: {project_id}")
        print(f"Run directory: {run_dir.name}")
        print(f"{'='*60}")

        # Step 1: Generate code with OpenHands
        print(f"  Step 1: Generating code (without logs)...")

        result = generator.generate_from_instruction(
            project_id=project_id,
            instruction=entry.get('instruction', ''),
            category=entry.get('Category', {}),
            ui_instruct=entry.get('ui_instruct', []),
            output_dir=run_dir,
        )

        # Copy task file to run directory
        if result.get("task_file"):
            task_src = Path(result["task_file"])
            if task_src.exists():
                shutil.copy(task_src, run_dir / "task.txt")

        # Save generation report
        gen_report = {
            "project_id": project_id,
            "run_id": run_id,
            "status": result["status"],
            "returncode": result["returncode"],
            "output_path": result.get("output_path"),
            "timestamp": datetime.now().isoformat(),
        }
        with open(run_dir / "generation_report.json", 'w') as f:
            json.dump(gen_report, f, indent=2)

        if result["status"] != "completed":
            print(f"  Generation failed: {result.get('returncode')}")
            results.append({
                "project_id": project_id,
                "run_id": run_id,
                "status": "failed",
                "step": "generation"
            })
            failed += 1
            continue

        print(f"  Generation completed: {result['output_path']}")

        task_context = build_task_context(entry)

        # Step 2: Inject logs using selected injector
        project_dir = Path(result["output_path"])
        if logging_mode == "compare":
            print("  Step 2: Comparing AST injection vs LLM patch injection...")
            log_result = run_injection_comparison(project_dir, project_id, task_context, run_dir)
            with open(run_dir / "log_injection_report.json", 'w') as f:
                json.dump(log_result, f, indent=2)

            ast_status = log_result.get("ast", {}).get("status")
            llm_status = log_result.get("llm", {}).get("status")
            overall_status = "completed" if ast_status == "completed" and llm_status == "completed" else "failed"
            results.append({
                "project_id": project_id,
                "run_id": run_id,
                "status": overall_status,
                "log_status": {
                    "ast": ast_status,
                    "llm": llm_status,
                },
            })

            if overall_status == "completed":
                print("  Comparison completed")
                processed += 1
            else:
                print("  Comparison failed")
                failed += 1
        else:
            print(f"  Step 2: Injecting semantic logs ({logging_mode})...")
            log_result = run_selected_injector(logging_mode, project_dir, task_context)

            with open(run_dir / "log_injection_report.json", 'w') as f:
                json.dump({
                    "project_id": project_id,
                    "run_id": run_id,
                    "logging_mode": logging_mode,
                    "status": log_result["status"],
                    "files_processed": log_result.get("files_processed", 0),
                    "files_modified": log_result.get("files_modified", 0),
                    "files_with_patch": log_result.get("files_with_patch", 0),
                    "errors": log_result.get("errors", []),
                    "timestamp": datetime.now().isoformat(),
                }, f, indent=2)

            results.append({
                "project_id": project_id,
                "run_id": run_id,
                "status": "completed" if log_result["status"] == "completed" else "failed",
                "log_status": log_result["status"],
                "logging_mode": logging_mode,
            })

            if log_result["status"] == "completed":
                print("  Log injection completed")
                processed += 1
            else:
                print("  Log injection failed")
                failed += 1

    summary = {
        "timestamp": datetime.now().strftime('%Y%m%d_%H%M%S'),
        "base_output_dir": str(base_output_path),
        "processed": processed,
        "failed": failed,
        "results": results,
    }

    summary_file = base_output_path / f"pipeline_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print("Pipeline Complete")
    print(f"{'='*60}")
    print(f"Processed: {processed}")
    print(f"Failed: {failed}")
    print(f"Summary saved to: {summary_file}")

    return summary


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenHands Generation with Semantic Logging")
    parser.add_argument("--input", default="data/test.jsonl", help="Input test.jsonl file")
    parser.add_argument("--output", default="openhands_runs", help="Base output directory")
    parser.add_argument("--single", help="Process only this specific ID")
    parser.add_argument("--start", help="Start ID (inclusive)")
    parser.add_argument("--end", help="End ID (inclusive)")
    parser.add_argument("--skip-logging", action="store_true", help="Skip log injection step")
    parser.add_argument(
        "--logging-mode",
        choices=["llm", "ast", "compare"],
        default="llm",
        help="Choose log injection mode: llm patch injection, ast injection, or compare both",
    )

    args = parser.parse_args()

    if args.single:
        input_path = Path(args.input)
        with open(input_path, 'r') as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get('id') == args.single:
                    project_id = entry.get('id', '')

                    # Create unique run directory
                    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{project_id}"
                    run_dir = Path(args.output) / run_id
                    run_dir.mkdir(parents=True, exist_ok=True)

                    generator = OpenHandsCodeGenerator()
                    print(f"Step 1: Generating project {project_id}...")
                    print(f"Run directory: {run_dir.name}")

                    result = generator.generate_from_instruction(
                        project_id=project_id,
                        instruction=entry.get('instruction', ''),
                        category=entry.get('Category', {}),
                        ui_instruct=entry.get('ui_instruct', []),
                        output_dir=run_dir,
                    )

                    # Save task file
                    if result.get("task_file"):
                        shutil.copy(result["task_file"], run_dir / "task.txt")

                    # Save generation report
                    with open(run_dir / "generation_report.json", 'w') as f:
                        json.dump({
                            "project_id": project_id,
                            "run_id": run_id,
                            "status": result["status"],
                            "output_path": result.get("output_path"),
                            "timestamp": datetime.now().isoformat(),
                        }, f, indent=2)

                    print(json.dumps(result, indent=2))

                    if not args.skip_logging and result["status"] == "completed":
                        task_context = build_task_context(entry)
                        project_dir = Path(result["output_path"])

                        if args.logging_mode == "compare":
                            print("\nStep 2: Comparing AST and LLM log injection...")
                            log_result = run_injection_comparison(project_dir, project_id, task_context, run_dir)
                        else:
                            print(f"\nStep 2: Injecting logs ({args.logging_mode})...")
                            log_result = run_selected_injector(args.logging_mode, project_dir, task_context)

                        with open(run_dir / "log_injection_report.json", 'w') as f:
                            json.dump(log_result, f, indent=2)

                        print(json.dumps(log_result, indent=2))
                    break
    else:
        run_pipeline(
            input_file=args.input,
            base_output_dir=args.output,
            start_id=args.start,
            end_id=args.end,
            logging_mode=args.logging_mode,
        )