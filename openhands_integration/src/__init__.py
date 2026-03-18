"""
OpenHands Integration for Fullstack Generation with Logging/Tracing

This module integrates OpenHands agent framework with our fullstack generation pipeline
to enable:
1. Agent-based code generation
2. Pause-and-inject logging at generation checkpoints
3. Comparative analysis between logged and non-logged runs
"""

import os
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import tempfile
import yaml

# ============================================================================
# Configuration
# ============================================================================

OPENHANDS_CONFIG = {
    "agent": {
        "model": os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-20250514"),
        "provider": os.getenv("LLM_PROVIDER", "anthropic"),
        "api_key": os.getenv("LLM_API_KEY", ""),
        "base_url": os.getenv("LLM_BASE_URL", ""),
    },
    "runtime": {
        "workspace_dir": "./openhands_workspace",
        "max_iterations": 50,
        "timeout": 3600,  # 1 hour
    },
    "logging": {
        "enable_trace": True,
        "trace_dir": "./logging_traces",
        "pause_after_generation": True,
    }
}


# ============================================================================
# OpenHands Agent Runner
# ============================================================================

class OpenHandsAgent:
    """Wrapper for OpenHands agent operations"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = {**OPENHANDS_CONFIG, **(config or {})}
        self.workspace = Path(self.config["runtime"]["workspace_dir"])
        self.trace_dir = Path(self.config["logging"]["trace_dir"])
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def run_task(
        self,
        task: str,
        task_id: str,
        pause_after_generation: bool = True,
        headless: bool = True,
    ) -> Dict[str, Any]:
        """
        Run an OpenHands task with optional pause for logging injection

        Returns:
            {
                "status": "completed" | "paused" | "failed",
                "conversation_id": str,
                "workspace_path": str,
                "trajectory": list of actions,
                "logs": list of log entries
            }
        """
        # Prepare workspace for this task
        task_workspace = self.workspace / f"task_{task_id}"
        task_workspace.mkdir(parents=True, exist_ok=True)

        # Prepare task file
        task_file = task_workspace / "task.txt"
        task_file.write_text(task)

        # Build OpenHands command
        cmd = [
            "openhands",
            "--headless" if headless else "--web",
            "-f", str(task_file),
            "--json",
        ]

        # Set environment variables for LLM
        env = os.environ.copy()
        if self.config["agent"]["api_key"]:
            env["LLM_API_KEY"] = self.config["agent"]["api_key"]
        if self.config["agent"]["base_url"]:
            env["LLM_BASE_URL"] = self.config["agent"]["base_url"]
        env["LLM_MODEL"] = self.config["agent"]["model"]

        # Run OpenHands
        result = self._run_openhands(cmd, env, task_workspace)

        return result

    def _run_openhands(
        self,
        cmd: List[str],
        env: Dict,
        workspace: Path
    ) -> Dict[str, Any]:
        """Execute OpenHands command and capture output"""

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=str(workspace),
                text=True,
            )

            output_lines = []
            for line in process.stdout:
                output_lines.append(line)
                # Parse JSON output if available
                if line.startswith("{") and line.strip().endswith("}"):
                    try:
                        event = json.loads(line)
                        # Handle events
                    except json.JSONDecodeError:
                        pass

            process.wait(timeout=self.config["runtime"]["timeout"])
            returncode = process.returncode

            return {
                "status": "completed" if returncode == 0 else "failed",
                "returncode": returncode,
                "output": "".join(output_lines),
                "workspace": str(workspace),
            }

        except subprocess.TimeoutExpired:
            process.kill()
            return {"status": "timeout", "workspace": str(workspace)}
        except Exception as e:
            return {"status": "error", "error": str(e), "workspace": str(workspace)}


# ============================================================================
# Fullstack Project Generator with OpenHands
# ============================================================================

class FullstackOpenHandsGenerator:
    """
    Generates fullstack projects using OpenHands agent with logging/tracing support

    Workflow:
    1. Generate initial project structure via OpenHands
    2. PAUSE - inject logging module
    3. Continue optimization with logging enabled
    4. Compare with non-logged version
    """

    def __init__(self, config: Optional[Dict] = None):
        self.oh_agent = OpenHandsAgent(config)
        self.base_prompt = self._load_base_prompt()

    def _load_base_prompt(self) -> str:
        """Load the base prompt for fullstack generation"""
        return """You are a professional fullstack developer. Generate a complete web application with:

1. Backend (Node.js/Express):
   - RESTful API endpoints
   - Proper error handling
   - Input validation

2. Frontend (React):
   - Responsive UI
   - State management
   - API integration

3. Structure:
   - backend/
     - app.js (Express server)
     - routes/
     - controllers/
     - models/
     - package.json
   - frontend/
     - src/
       - App.jsx
       - components/
       - api/
     - package.json

Generate complete, working code. No placeholders or TODOs.
"""

    def generate_project(
        self,
        project_name: str,
        requirements: str,
        inject_logging: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a fullstack project

        Args:
            project_name: Name of the project
            requirements: Detailed requirements
            inject_logging: Whether to inject logging/tracing module

        Returns:
            Project generation result with trajectory for analysis
        """

        # Build generation task
        task = f"""Create a new fullstack project called '{project_name}'.

Requirements:
{requirements}

Working directory: /workspace/{project_name}

Steps:
1. Create the project structure
2. Generate backend code (Express, Node.js)
3. Generate frontend code (React)
4. Ensure package.json has all dependencies
5. Verify the code compiles/runs without errors
"""

        task_id = f"{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Run OpenHands agent
        result = self.oh_agent.run_task(
            task=task,
            task_id=task_id,
            pause_after_generation=inject_logging,
        )

        return {
            "project_name": project_name,
            "task_id": task_id,
            "result": result,
            "logging_enabled": inject_logging,
        }


# ============================================================================
# Logging Injection Module
# ============================================================================

class LoggingInjector:
    """Injects logging/tracing into generated projects"""

    def inject(self, project_path: str, trace_id: str) -> Dict[str, Any]:
        """
        Inject logging module into project

        Args:
            project_path: Path to generated project
            trace_id: Unique identifier for this trace

        Returns:
            Injection result
        """
        project = Path(project_path)

        injections = {
            "backend": self._inject_backend_logging(project / "backend", trace_id),
            "frontend": self._inject_frontend_logging(project / "frontend", trace_id),
        }

        return {
            "trace_id": trace_id,
            "project": str(project),
            "injections": injections,
            "timestamp": datetime.now().isoformat(),
        }

    def _inject_backend_logging(self, backend_path: Path, trace_id: str) -> bool:
        """Inject logging into backend"""
        if not backend_path.exists():
            return False

        # Add correlation ID middleware
        middleware_content = '''
// Logging middleware - injected by OpenHands integration
const crypto = require('crypto');

function correlationIdMiddleware(req, res, next) {
    req.traceId = req.headers['x-trace-id'] || crypto.randomUUID();
    res.setHeader('x-trace-id', req.traceId);
    console.log(`[TRACE:${req.traceId}] ${req.method} ${req.path}`);
    next();
}

module.exports = { correlationIdMiddleware };
'''

        middleware_path = backend_path / "middleware" / "logging.js"
        middleware_path.parent.mkdir(exist_ok=True)
        middleware_path.write_text(middleware_content)

        # Modify app.js to use middleware
        app_js = backend_path / "app.js"
        if app_js.exists():
            content = app_js.read_text()
            if "correlationIdMiddleware" not in content:
                content = content.replace(
                    "const express = require('express');",
                    "const express = require('express');\nconst { correlationIdMiddleware } = require('./middleware/logging');"
                )
                content = content.replace(
                    "app.use(",
                    "app.use(correlationIdMiddleware);\napp.use("
                )
                app_js.write_text(content)

        return True

    def _inject_frontend_logging(self, frontend_path: Path, trace_id: str) -> bool:
        """Inject logging into frontend"""
        if not frontend_path.exists():
            return False

        # Add fetch interceptor
        interceptor_content = '''
// Tracing interceptor - injected by OpenHands integration
(function() {
    const originalFetch = window.fetch;
    const traceId = localStorage.getItem('trace_id') || '${traceId}';

    window.fetch = async function(...args) {
        const headers = new Headers(args[1]?.headers || {});
        headers.set('x-trace-id', traceId);

        console.log(`[TRACE:${traceId}] FETCH ${args[0]}`, {
            method: args[1]?.method || 'GET',
            headers: Object.fromEntries(headers)
        });

        try {
            const response = await originalFetch(args[0], { ...args[1], headers });
            console.log(`[TRACE:${traceId}] RESPONSE ${args[0]}`, { status: response.status });
            return response;
        } catch (error) {
            console.error(`[TRACE:${traceId}] ERROR ${args[0]}`, error.message);
            throw error;
        }
    };

    // Capture console logs
    const originalConsole = { ...console };
    ['log', 'error', 'warn', 'info'].forEach(method => {
        console[method] = function(...args) {
            originalConsole[method].apply(console, [`[TRACE:${traceId}]`, ...args]);
        };
    });
})();
'''

        # Inject into index.html or main entry
        index_html = frontend_path / "public" / "index.html"
        if index_html.exists():
            content = index_html.read_text()
            if "Tracing interceptor" not in content:
                injection = f'<script>{interceptor_content}</script>'
                content = content.replace("</body>", f"{injection}</body>")
                index_html.write_text(content)

        return True


# ============================================================================
# Comparative Analysis
# ============================================================================

class ComparativeAnalyzer:
    """Compare logged vs non-logged optimization runs"""

    def __init__(self, trace_dir: str):
        self.trace_dir = Path(trace_dir)

    def load_trace(self, trace_id: str) -> Dict[str, Any]:
        """Load a single trace"""
        trace_file = self.trace_dir / f"{trace_id}.json"
        if trace_file.exists():
            return json.loads(trace_file.read_text())
        return None

    def compare_runs(
        self,
        run_a_id: str,
        run_b_id: str,
    ) -> Dict[str, Any]:
        """
        Compare two runs (logged vs non-logged)

        Returns comparison metrics:
        - iterations_to_success
        - error_recovery_time
        - final_success_rate
        """
        trace_a = self.load_trace(run_a_id)
        trace_b = self.load_trace(run_b_id)

        if not trace_a or not trace_b:
            return {"error": "Missing traces"}

        return {
            "run_a": {
                "id": run_a_id,
                "iterations": trace_a.get("iterations", 0),
                "success": trace_a.get("success", False),
                "errors": trace_a.get("error_count", 0),
            },
            "run_b": {
                "id": run_b_id,
                "iterations": trace_b.get("iterations", 0),
                "success": trace_b.get("success", False),
                "errors": trace_b.get("error_count", 0),
            },
            "improvement": {
                "iterations_delta": trace_b.get("iterations", 0) - trace_a.get("iterations", 0),
                "error_reduction": trace_a.get("error_count", 0) - trace_b.get("error_count", 0),
            }
        }


# ============================================================================
# Main Pipeline
# ============================================================================

def run_comparative_experiment(
    project_requirements: str,
    project_name: str = "test_project",
) -> Dict[str, Any]:
    """
    Run comparative experiment: logged vs non-logged optimization

    Returns:
        Comparison results and recommendations
    """
    generator = FullstackOpenHandsGenerator()

    # Run without logging
    print("Running experiment WITHOUT logging injection...")
    result_no_log = generator.generate_project(
        project_name=f"{project_name}_no_log",
        requirements=project_requirements,
        inject_logging=False,
    )

    # Run with logging
    print("Running experiment WITH logging injection...")
    result_with_log = generator.generate_project(
        project_name=f"{project_name}_with_log",
        requirements=project_requirements,
        inject_logging=True,
    )

    # Compare results
    analyzer = ComparativeAnalyzer(generator.oh_agent.trace_dir)
    comparison = analyzer.compare_runs(
        result_no_log["task_id"],
        result_with_log["task_id"],
    )

    return {
        "experiment_timestamp": datetime.now().isoformat(),
        "project_name": project_name,
        "without_logging": result_no_log,
        "with_logging": result_with_log,
        "comparison": comparison,
    }


if __name__ == "__main__":
    # Example usage
    sample_requirements = """
    Create a simple stock price lookup application:
    - Backend API endpoint: GET /api/stock/:symbol returns stock info
    - Frontend: Search input for stock symbol, display result
    - Use mock data for stock prices
    """

    # Run single generation test
    generator = FullstackOpenHandsGenerator()
    result = generator.generate_project(
        project_name="stock_lookup",
        requirements=sample_requirements,
        inject_logging=True,
    )
    print(json.dumps(result, indent=2))
