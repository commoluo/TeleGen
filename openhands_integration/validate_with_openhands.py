"""
OpenHands Validation Pipeline for Fullstack Projects
====================================================

This pipeline:
1. Takes existing generated projects
2. Uses OpenHands to validate and fix code issues
3. Injects logging/tracing modules
4. Runs comparative tests (logged vs non-logged)

Usage:
    python validate_with_openhands.py --project <project_path> --task "fix the backend errors"
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
# Project Validation
# ============================================================================

class ProjectValidator:
    """Validates and fixes generated projects using OpenHands"""

    def __init__(self, project_path: str, config: Optional[Dict] = None):
        self.project_path = Path(project_path)
        self.config = config or {}
        self.workspace = Path(self.config.get("workspace_dir", "./openhands_workspace"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.validation_log = []

    def validate_project(self, task: str = "Check for common code issues and fix them") -> Dict[str, Any]:
        """
        Validate a project using OpenHands agent

        Args:
            task: The validation/fix task for OpenHands

        Returns:
            Validation result with trajectory
        """
        # Create task workspace
        task_id = f"validate_{self.project_path.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        task_workspace = self.workspace / task_id
        task_workspace.mkdir(parents=True, exist_ok=True)

        # Copy project to workspace
        workspace_project = task_workspace / "project"
        shutil.copytree(self.project_path, workspace_project)

        # Create validation task
        validation_prompt = f"""You are validating a generated fullstack project.

Project location: {workspace_project}

Your task: {task}

Steps to perform:
1. Explore the project structure ({workspace_project})
2. Check backend code for issues:
   - Missing dependencies in package.json
   - Syntax errors in JavaScript/TypeScript
   - Missing module imports
   - Incorrect Express route handlers
3. Check frontend code for issues:
   - Missing React component exports
   - Incorrect import paths
   - package.json script issues
4. If issues found, fix them
5. Report what was checked and what was fixed/not fixed

Be thorough - these projects often have subtle bugs.
"""

        # Write task file
        task_file = task_workspace / "task.txt"
        task_file.write_text(validation_prompt)

        # Run OpenHands
        result = self._run_openhands_validation(task_file, task_workspace)

        return {
            "task_id": task_id,
            "project": str(self.project_path),
            "workspace": str(workspace_project),
            "task": task,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        }

    def _run_openhands_validation(self, task_file: Path, workspace: Path) -> Dict[str, Any]:
        """Run OpenHands validation"""

        # Use absolute path for task file since we're changing cwd
        task_file = task_file.resolve()
        workspace = workspace.resolve()

        cmd = [
            "openhands",
            "--headless",
            "--always-approve",
            "--override-with-envs",
            "-f", str(task_file),
        ]

        # Use Qwen via OpenAI-compatible API
        # litellm requires format "provider/model-name" for custom endpoints
        env = dict(os.environ)
        qwen_key = env.get("QWEN_API_KEY") or env.get("WEBVOYAGER_API_KEY")
        if qwen_key:
            env["LLM_API_KEY"] = qwen_key
            qwen_model = os.getenv("QWEN_MODEL", "qwen3.5-plus")
            env["LLM_MODEL"] = f"openai/{qwen_model}"  # litellm needs openai/provider format
            env["LLM_PROVIDER"] = "openai"
            env["LLM_BASE_URL"] = os.getenv("QWEN_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            print(f"Using Qwen for validation ({qwen_model})")
        elif "DEEPSEEK_API_KEY" in env:
            env["LLM_API_KEY"] = env["DEEPSEEK_API_KEY"]
            env["LLM_MODEL"] = "deepseek/deepseek-chat"  # Must use provider/model format
            env["LLM_PROVIDER"] = "deepseek"
            env["LLM_BASE_URL"] = "https://api.deepseek.com"
            print("DEBUG: Using DeepSeek for validation")
        elif "OPENAI_API_KEY" in env:
            env["LLM_API_KEY"] = env["OPENAI_API_KEY"]
            env["LLM_MODEL"] = "gpt-4o"
            env["LLM_PROVIDER"] = "openai"
            env["LLM_BASE_URL"] = "https://api.openai.com/v1"
            print("DEBUG: Using OpenAI for validation")
        else:
            print("DEBUG: No API key found!")

        # Help with non-interactive terminal detection
        env["TTY_INTERACTIVE"] = "1"

        try:
            result = subprocess.run(
                cmd,
                cwd=str(workspace),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.config.get("timeout", 1800),
            )

            return {
                "returncode": result.returncode,
                "stdout": result.stdout[:5000] if result.stdout else "",
                "stderr": result.stderr[:2000] if result.stderr else "",
            }

        except subprocess.TimeoutExpired:
            return {"returncode": -1, "error": "timeout"}
        except Exception as e:
            return {"returncode": -1, "error": str(e)}


# ============================================================================
# Logging Injector
# ============================================================================

class LoggingInjector:
    """Injects logging/tracing into validated projects"""

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
                # Add require
                content = content.replace(
                    "const express = require('express');",
                    "const express = require('express');\nconst { tracingMiddleware } = require('./middleware/tracing');"
                )
                # Add middleware usage
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

def run_validation_pipeline(
    project_path: str,
    validation_task: str = "Check for common code issues and fix them",
    inject_logging: bool = True,
    output_dir: str = "./validation_results",
) -> Dict[str, Any]:
    """
    Run the full validation pipeline

    Args:
        project_path: Path to the project to validate
        validation_task: Task description for OpenHands
        inject_logging: Whether to inject logging after validation
        output_dir: Where to save results

    Returns:
        Pipeline results
    """
    project_path = Path(project_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "project": str(project_path),
        "timestamp": datetime.now().isoformat(),
        "steps": [],
    }

    # Step 1: Validate with OpenHands
    print(f"Step 1: Validating project {project_path.name}...")
    validator = ProjectValidator(project_path, OPENHANDS_CONFIG)
    validation_result = validator.validate_project(validation_task)
    results["steps"].append({
        "step": "validation",
        "result": validation_result,
    })

    # Save validation result
    validation_output = output_dir / f"{project_path.name}_validation.json"
    with open(validation_output, "w") as f:
        json.dump(validation_result, f, indent=2)
    print(f"  Validation saved to: {validation_output}")

    # Step 2: Inject logging
    if inject_logging:
        print(f"Step 2: Injecting logging to validated project...")
        injector = LoggingInjector()

        # Use the workspace project (the validated/copied version)
        validated_project = validation_result.get("workspace", str(project_path))
        log_result = injector.inject_to_project(validated_project)
        results["steps"].append({
            "step": "logging_injection",
            "result": log_result,
        })

        logging_output = output_dir / f"{project_path.name}_logging.json"
        with open(logging_output, "w") as f:
            json.dump(log_result, f, indent=2)
        print(f"  Logging injection saved to: {logging_output}")

    results["status"] = "completed"
    print(f"Pipeline completed: {output_dir}")

    return results


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate projects with OpenHands")
    parser.add_argument("--project", required=True, help="Path to project to validate")
    parser.add_argument("--task", default="Check for common code issues and fix them",
                        help="Validation task for OpenHands")
    parser.add_argument("--no-logging", action="store_true", help="Skip logging injection")
    parser.add_argument("--output", default="./validation_results", help="Output directory")

    args = parser.parse_args()

    results = run_validation_pipeline(
        project_path=args.project,
        validation_task=args.task,
        inject_logging=not args.no_logging,
        output_dir=args.output,
    )

    print("\n" + "="*60)
    print("Pipeline Results Summary:")
    print(f"Project: {results['project']}")
    print(f"Steps completed: {len(results['steps'])}")
    for step in results['steps']:
        print(f"  - {step['step']}")
    print(f"Status: {results['status']}")
