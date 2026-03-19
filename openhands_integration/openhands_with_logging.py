"""
OpenHands Generation with Semantic Logging Pipeline
================================================

Two-step process:
1. Generate fullstack code with OpenHands (without logs)
2. Inject semantic logs using dedicated LLM log injector (fast)

Usage:
    python openhands_with_logging.py --single 000001
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
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
# OpenHands Step 1: Generate Code Without Logs
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
        if "MINIMAX_API_KEY" in env:
            env["LLM_API_KEY"] = env["MINIMAX_API_KEY"]
            minimax_model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
            env["LLM_MODEL"] = f"openai/{minimax_model}"
            env["LLM_PROVIDER"] = "openai"
            env["LLM_BASE_URL"] = "https://api.minimaxi.com/v1"
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
        output_path = output_dir / f"project_{project_id}"

        possible_sources = [
            task_workspace / "workspace" / f"project_{project_id}",
            task_workspace / "workspace",
            task_workspace / f"project_{project_id}",
            task_workspace,
        ]

        for src in possible_sources:
            if src.exists():
                backend = src / "backend" if src != task_workspace else None
                if backend and backend.exists():
                    if output_path.exists():
                        shutil.rmtree(output_path)
                    shutil.copytree(src, output_path)
                    return output_path
                elif src != task_workspace:
                    if (src / "backend").exists():
                        if output_path.exists():
                            shutil.rmtree(output_path)
                        shutil.copytree(src, output_path)
                        return output_path

        if (task_workspace / "backend").exists():
            if output_path.exists():
                shutil.rmtree(output_path)
            shutil.copytree(task_workspace, output_path)
            return output_path

        return None


# ============================================================================
# Main Pipeline
# ============================================================================

def run_pipeline(
    input_file: str = "data/test.jsonl",
    output_dir: str = "openhands_generated",
    start_id: Optional[str] = None,
    end_id: Optional[str] = None,
):
    input_path = Path(input_file)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generator = OpenHandsCodeGenerator()
    log_injector = SemanticLogInjector()  # Fast LLM-based injector, NOT OpenHands

    results = []
    processed = 0
    failed = 0

    print(f"Reading from: {input_path}")
    print(f"Output directory: {output_path}")

    with open(input_path, 'r') as f:
        lines = f.readlines()

    for line in lines:
        entry = json.loads(line.strip())
        project_id = entry.get('id', '')

        if start_id and project_id < start_id:
            continue
        if end_id and project_id > end_id:
            break

        print(f"\n{'='*60}")
        print(f"Processing project: {project_id}")
        print(f"{'='*60}")

        project_dir = output_path / f"project_{project_id}"
        if project_dir.exists():
            print(f"  Project already exists, skipping generation...")
        else:
            print(f"  Step 1: Generating code (without logs)...")
            result = generator.generate_from_instruction(
                project_id=project_id,
                instruction=entry.get('instruction', ''),
                category=entry.get('Category', {}),
                ui_instruct=entry.get('ui_instruct', []),
                output_dir=output_path,
            )

            if result["status"] != "completed":
                print(f"  Generation failed: {result.get('returncode')}")
                results.append({"project_id": project_id, "status": "failed", "step": "generation"})
                failed += 1
                continue

            print(f"  Generation completed: {result['output_path']}")

        print(f"  Step 2: Injecting semantic logs (LLM log injector)...")
        log_result = log_injector.inject_to_project(str(project_dir))

        results.append({
            "project_id": project_id,
            "status": "completed" if log_result["status"] == "completed" else "failed",
            "log_status": log_result["status"],
        })

        if log_result["status"] == "completed":
            print(f"  Log injection completed")
            processed += 1
        else:
            print(f"  Log injection failed")
            failed += 1

    summary = {
        "timestamp": datetime.now().strftime('%Y%m%d_%H%M%S'),
        "processed": processed,
        "failed": failed,
        "results": results,
    }

    summary_file = output_path / f"pipeline_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
    parser.add_argument("--output", default="openhands_generated", help="Output directory")
    parser.add_argument("--single", help="Process only this specific ID")
    parser.add_argument("--start", help="Start ID (inclusive)")
    parser.add_argument("--end", help="End ID (inclusive)")
    parser.add_argument("--skip-logging", action="store_true", help="Skip log injection step")

    args = parser.parse_args()

    if args.single:
        input_path = Path(args.input)
        with open(input_path, 'r') as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get('id') == args.single:
                    generator = OpenHandsCodeGenerator()
                    log_injector = SemanticLogInjector()  # Fast LLM injector

                    print(f"Step 1: Generating project {args.single}...")
                    result = generator.generate_from_instruction(
                        project_id=entry.get('id', ''),
                        instruction=entry.get('instruction', ''),
                        category=entry.get('Category', {}),
                        ui_instruct=entry.get('ui_instruct', []),
                        output_dir=Path(args.output),
                    )
                    print(json.dumps(result, indent=2))

                    if not args.skip_logging and result["status"] == "completed":
                        print(f"\nStep 2: Injecting logs (LLM log injector)...")
                        log_result = log_injector.inject_to_project(result["output_path"])
                        print(json.dumps(log_result, indent=2))
                    break
    else:
        run_pipeline(
            input_file=args.input,
            output_dir=args.output,
            start_id=args.start,
            end_id=args.end,
        )