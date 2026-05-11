"""
OpenHands Direct Generation Pipeline
=====================================

This pipeline:
1. Reads test.jsonl entries
2. Uses OpenHands to generate fullstack projects DIRECTLY from instructions
3. Skips the api_doc generation step
4. Injects logging/tracing modules
5. Validates generated code

Usage:
    python openhands_direct_generator.py --input data/test.jsonl --output generated_projects
    python openhands_direct_generator.py --single 000001
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

# Load .env file from alternative_generation directory
env_path = Path(__file__).parent.parent / "alternative_generation" / ".env"
if env_path.exists():
    load_dotenv(env_path)

# ============================================================================
# Configuration
# ============================================================================

OPENHANDS_CONFIG = {
    "workspace_dir": "./openhands_workspace",
    "timeout": 1800,  # 30 minutes
}


# ============================================================================
# OpenHands Generator
# ============================================================================

class OpenHandsDirectGenerator:
    """
    Generates fullstack projects directly using OpenHands agent

    Takes test.jsonl entries and generates complete projects without
    intermediate api_doc step.
    """

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
        """
        Generate a fullstack project directly from test.jsonl instruction

        Args:
            project_id: ID from test.jsonl (e.g., "000001")
            instruction: The main instruction text
            category: Category information
            ui_instruct: UI instruction details
            output_dir: Where to save the generated project

        Returns:
            Generation result with status and workspace path
        """
        # Build comprehensive task for OpenHands
        task = self._build_generation_task(
            project_id, instruction, category, ui_instruct
        )

        # Create task workspace
        task_id = f"gen_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        task_workspace = self.workspace / task_id
        task_workspace.mkdir(parents=True, exist_ok=True)

        # Write task file
        task_file = task_workspace / "task.txt"
        task_file.write_text(task)

        # Run OpenHands
        result = self._run_openhands_generation(task_file, task_workspace)

        # Copy result to output directory
        generated_project = task_workspace / "workspace"
        if generated_project.exists():
            output_path = output_dir / f"project_{project_id}"
            if output_path.exists():
                shutil.rmtree(output_path)
            shutil.copytree(generated_project, output_path)
        else:
            # OpenHands might put files directly in task_workspace
            # Check if task_workspace itself contains backend/frontend
            if (task_workspace / "backend").exists() and (task_workspace / "frontend").exists():
                output_path = output_dir / f"project_{project_id}"
                if output_path.exists():
                    shutil.rmtree(output_path)
                shutil.copytree(task_workspace, output_path)
            else:
                # Look for project_* subdirectory
                subdirs = list(task_workspace.glob("project_*"))
                if subdirs:
                    src_dir = subdirs[0]
                    output_path = output_dir / f"project_{project_id}"
                    if output_path.exists():
                        shutil.rmtree(output_path)
                    shutil.copytree(src_dir, output_path)
                else:
                    # Fallback: copy entire workspace
                    output_path = output_dir / f"project_{project_id}"
                    if output_path.exists():
                        shutil.rmtree(output_path)
                    shutil.copytree(task_workspace, output_path)

        return {
            "project_id": project_id,
            "task_id": task_id,
            "status": "completed" if result["returncode"] == 0 else "failed",
            "returncode": result["returncode"],
            "output_path": str(output_path),
            "stdout": result.get("stdout", "")[:5000],
        }

    def _build_generation_task(
        self,
        project_id: str,
        instruction: str,
        category: Dict,
        ui_instruct: List[Dict],
    ) -> str:
        """Build a comprehensive generation task for OpenHands"""

        # Extract UI requirements from ui_instruct
        ui_requirements = self._extract_ui_requirements(ui_instruct)

        task = f"""You are a professional fullstack developer. Generate a complete, working web application.

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
   - RESTful API endpoints (design appropriate endpoints based on the requirement)
   - Proper error handling with consistent JSON response format: {{"success": true/false, "data": ..., "error": ...}}
   - Input validation
   - CORS enabled
   - Port: 5001

2. **Frontend (React)**:
   - Responsive UI design
   - State management
   - API integration with backend
   - Build tool: Vite (use npm create vite@latest)
   - Port: 3000

3. **Project Structure**:
```
project_{project_id}/
├── backend/
│   ├── app.js (Express server entry point)
│   ├── routes/ (API route handlers)
│   ├── controllers/ (Business logic)
│   ├── data/ (Mock data)
│   ├── middleware/ (Custom middleware)
│   └── package.json
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── components/
│   │   └── api/
│   ├── public/
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## Design Requirements:
- Background color: {self._extract_color(instruction, 'background')}
- Component color: {self._extract_color(instruction, 'component')}

## Implementation Steps:
1. Create the project directory structure
2. Generate backend code with Express
3. Generate frontend code with React + Vite
4. Create package.json files with all necessary dependencies
5. Verify the code has no syntax errors (run node --check on .js files)
6. Make sure the application can start without errors

## Important:
- Generate COMPLETE, WORKING code. No placeholders, TODOs, or incomplete implementations.
- All files must be fully implemented and syntactically correct.
- Follow REST best practices for API design.
- Use modern JavaScript (ES6+).
"""

        return task

    def _extract_ui_requirements(self, ui_instruct: List[Dict]) -> str:
        """Extract UI requirements from ui_instruct list"""
        if not ui_instruct:
            return "Standard web application interface"

        requirements = []
        for item in ui_instruct[:3]:  # Take first 3 UI instructions
            task = item.get('task', '')
            expected = item.get('expected_result', '')
            if task:
                requirements.append(f"- Task: {task}")
            if expected:
                requirements.append(f"  Expected: {expected}")
        return "\n".join(requirements) if requirements else "Standard web application"

    def _extract_color(self, instruction: str, color_type: str) -> str:
        """Extract color requirements from instruction"""
        import re

        # Look for patterns like "background color to white" or "background: white"
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

    def _run_openhands_generation(self, task_file: Path, workspace: Path) -> Dict[str, Any]:
        """Run OpenHands to generate the project"""

        cmd = [
            "openhands",
            "--headless",
            "--always-approve",
            "--override-with-envs",
            "-f", str(task_file.resolve()),
        ]

        env = dict(os.environ)

        # Use Qwen via OpenAI-compatible API
        qwen_key = env.get("QWEN_API_KEY") or env.get("WEBVOYAGER_API_KEY")
        if qwen_key:
            env["LLM_API_KEY"] = qwen_key
            qwen_model = os.getenv("QWEN_MODEL", "qwen3.5-plus")
            env["LLM_MODEL"] = f"openai/{qwen_model}"
            env["LLM_PROVIDER"] = "openai"
            env["LLM_BASE_URL"] = os.getenv("QWEN_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            print(f"  Using Qwen: {qwen_model}")

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


# ============================================================================
# Logging Injector
# ============================================================================

class LoggingInjector:
    """Injects logging/tracing into generated projects"""

    def inject_to_project(self, project_path: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Inject logging modules into a project"""
        if trace_id is None:
            trace_id = f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        project = Path(project_path)
        injections = []

        # Inject backend logging
        backend = project / "backend"
        if backend.exists():
            self._inject_backend_logging(backend, trace_id)
            injections.append("backend")

        # Inject frontend logging
        frontend = project / "frontend"
        if frontend.exists():
            self._inject_frontend_logging(frontend, trace_id)
            injections.append("frontend")

        return {
            "trace_id": trace_id,
            "injections": injections,
            "timestamp": datetime.now().isoformat(),
        }

    def _inject_backend_logging(self, backend_path: Path, trace_id: str):
        """Inject correlation ID middleware to backend"""
        middleware_dir = backend_path / "middleware"
        middleware_dir.mkdir(exist_ok=True)

        logging_middleware = middleware_dir / "tracing.js"
        logging_middleware.write_text(f'''// Tracing middleware - injected for analysis
const crypto = require('crypto');

const tracingMiddleware = (req, res, next) => {{
    req.traceId = req.headers['x-trace-id'] || crypto.randomUUID();
    res.setHeader('x-trace-id', req.traceId);

    const start = Date.now();
    res.on('finish', () => {{
        const duration = Date.now() - start;
        console.log(JSON.stringify({{
            type: 'request_trace',
            trace_id: req.traceId,
            method: req.method,
            path: req.path,
            status: res.statusCode,
            duration_ms: duration,
            timestamp: new Date().toISOString()
        }}));
    }});

    next();
}};

module.exports = {{ tracingMiddleware }};
''')

        # Update app.js to use middleware
        app_js = backend_path / "app.js"
        if app_js.exists():
            content = app_js.read_text()
            if "tracingMiddleware" not in content:
                content = content.replace(
                    "const express = require('express');",
                    "const express = require('express');\nconst { tracingMiddleware } = require('./middleware/tracing');"
                )
                content = content.replace(
                    "app.use(",
                    "app.use(tracingMiddleware);\napp.use("
                )
                app_js.write_text(content)

    def _inject_frontend_logging(self, frontend_path: Path, trace_id: str):
        """Inject fetch interceptor to frontend"""
        src = frontend_path / "src"
        if not src.exists():
            src = frontend_path

        tracing_content = f'''// Tracing interceptor - injected for analysis
(function() {{
    const traceId = '{trace_id}';
    localStorage.setItem('trace_id', traceId);

    const originalFetch = window.fetch;
    window.fetch = async function(url, options = {{}}) {{
        const headers = new Headers(options.headers || {{}});
        headers.set('x-trace-id', traceId);

        const startTime = Date.now();
        console.log(JSON.stringify({{
            type: 'fetch_start',
            trace_id: traceId,
            url: typeof url === 'string' ? url : url.toString(),
            timestamp: new Date().toISOString()
        }}));

        try {{
            const response = await originalFetch(url, {{ ...options, headers }});
            const duration = Date.now() - startTime;

            console.log(JSON.stringify({{
                type: 'fetch_complete',
                trace_id: traceId,
                url: typeof url === 'string' ? url : url.toString(),
                status: response.status,
                duration_ms: duration,
                timestamp: new Date().toISOString()
            }}));

            return response;
        }} catch (error) {{
            console.log(JSON.stringify({{
                type: 'fetch_error',
                trace_id: traceId,
                url: typeof url === 'string' ? url : url.toString(),
                error: error.message,
                timestamp: new Date().toISOString()
            }}));
            throw error;
        }}
    }};

    // Override console methods
    const methods = ['log', 'error', 'warn', 'info'];
    methods.forEach(method => {{
        const original = console[method];
        console[method] = (...args) => {{
            original.apply(console, [{{trace_id}} , ...args]);
        }};
    }});
}})();
'''

        # Try to inject into index.html
        index_html = None
        for candidate in [frontend_path / "public" / "index.html", frontend_path / "index.html"]:
            if candidate.exists():
                index_html = candidate
                break

        if index_html:
            content = index_html.read_text()
            if "Tracing interceptor" not in content:
                content = content.replace("</body>", f"<script>{tracing_content}</script>\n</body>")
                index_html.write_text(content)


# ============================================================================
# Main Pipeline
# ============================================================================

def run_pipeline(
    input_file: str = "data/test.jsonl",
    output_dir: str = "openhands_generated",
    start_id: Optional[str] = None,
    end_id: Optional[str] = None,
    inject_logging: bool = True,
):
    """
    Run the complete pipeline

    Args:
        input_file: Path to test.jsonl
        output_dir: Where to save generated projects
        start_id: Start processing from this ID (inclusive)
        end_id: Stop processing at this ID (inclusive)
        inject_logging: Whether to inject logging after generation
    """
    input_path = Path(input_file)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generator = OpenHandsDirectGenerator()
    injector = LoggingInjector()

    results = []
    processed = 0
    failed = 0

    print(f"Reading from: {input_path}")
    print(f"Output directory: {output_path}")

    # Read test.jsonl
    with open(input_path, 'r') as f:
        lines = f.readlines()

    for line in lines:
        entry = json.loads(line.strip())
        project_id = entry.get('id', '')

        # Filter by ID range if specified
        if start_id and project_id < start_id:
            continue
        if end_id and project_id > end_id:
            break

        print(f"\n{'='*60}")
        print(f"Processing project: {project_id}")
        print(f"{'='*60}")

        try:
            # Generate project directly from instruction
            result = generator.generate_from_instruction(
                project_id=project_id,
                instruction=entry.get('instruction', ''),
                category=entry.get('Category', {}),
                ui_instruct=entry.get('ui_instruct', []),
                output_dir=output_path,
            )

            # Inject logging if requested
            if inject_logging and result["status"] == "completed":
                log_result = injector.inject_to_project(
                    result["output_path"],
                    trace_id=f"gen_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                result["logging"] = log_result

            results.append(result)
            processed += 1

            if result["status"] == "completed":
                print(f"  Status: SUCCESS")
                print(f"  Output: {result['output_path']}")
            else:
                print(f"  Status: FAILED (returncode: {result['returncode']})")
                failed += 1

        except Exception as e:
            print(f"  Error: {str(e)}")
            results.append({"project_id": project_id, "status": "error", "error": str(e)})
            failed += 1

    # Save summary
    summary = {
        "timestamp": datetime.now().strftime('%Y%m%d_%H%M%S'),
        "input_file": str(input_path),
        "output_dir": str(output_path),
        "total": len(lines),
        "processed": processed,
        "failed": failed,
        "results": results,
    }

    summary_file = output_path / f"generation_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
    parser = argparse.ArgumentParser(description="OpenHands Direct Generation Pipeline")
    parser.add_argument("--input", default="data/test.jsonl", help="Input test.jsonl file")
    parser.add_argument("--output", default="openhands_generated", help="Output directory")
    parser.add_argument("--single", help="Process only this specific ID")
    parser.add_argument("--start", help="Start ID (inclusive)")
    parser.add_argument("--end", help="End ID (inclusive)")
    parser.add_argument("--no-logging", action="store_true", help="Skip logging injection")

    args = parser.parse_args()

    if args.single:
        # Run for single ID
        input_path = Path(args.input)
        with open(input_path, 'r') as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get('id') == args.single:
                    generator = OpenHandsDirectGenerator()
                    injector = LoggingInjector()

                    result = generator.generate_from_instruction(
                        project_id=entry.get('id', ''),
                        instruction=entry.get('instruction', ''),
                        category=entry.get('Category', {}),
                        ui_instruct=entry.get('ui_instruct', []),
                        output_dir=Path(args.output),
                    )

                    print(json.dumps(result, indent=2))

                    if not args.no_logging and result["status"] == "completed":
                        log_result = injector.inject_to_project(result["output_path"])
                        print("\nLogging injected:")
                        print(json.dumps(log_result, indent=2))
                    break
    else:
        # Run full pipeline
        run_pipeline(
            input_file=args.input,
            output_dir=args.output,
            start_id=args.start,
            end_id=args.end,
            inject_logging=not args.no_logging,
        )