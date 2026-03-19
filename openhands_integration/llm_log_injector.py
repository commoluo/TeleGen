"""
LLM-based Semantic Log Injector
===============================

Directly uses LLM API to inject semantic logs into code files.
Fast and lightweight - one API call per file.

Usage:
    python llm_log_injector.py --project openhands_generated/project_000002
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv
import httpx

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env
env_path = Path(__file__).parent.parent / "alternative_generation" / ".env"
if env_path.exists():
    load_dotenv(env_path)


# ============================================================================
# LLM Client
# ============================================================================

class MiniMaxLLMClient:
    """Simple MiniMax API client for log injection"""

    def __init__(self):
        self.api_key = os.getenv("MINIMAX_API_KEY", "")
        self.base_url = "https://api.minimaxi.com/v1"
        self.model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7-highspeed")

    def inject_logs(self, file_path: Path, file_content: str) -> str:
        """
        Send file to LLM and get back content with semantic logs added.
        Returns the modified content.
        """
        prompt = self._build_prompt(file_content, file_path.suffix)

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 8000,
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"    Error calling API: {e}")
            return None

    def _build_prompt(self, content: str, file_ext: str) -> str:
        """Build prompt for log injection"""

        if file_ext in ['.jsx', '.tsx', '.js']:
            lang = "JavaScript/React"
        else:
            lang = "JavaScript"

        return f"""You are adding SEMANTIC logging to existing {lang} code.

## CRITICAL RULES:
1. ONLY add console.log statements - do NOT modify any other code
2. Do NOT change business logic, algorithms, or code structure
3. Only add NEW lines with logging at important points

## Logging Format:
- Backend API: console.log("[API] " + req.method + " " + req.path + " params:" + JSON.stringify(req.params));
- Backend data: console.log("[DATA] operation result count: " + result.length);
- Frontend render: console.log("[RENDER] ComponentName");
- Frontend API call: console.log("[API_CALL] endpoint:" + url);
- Frontend interaction: console.log("[ACTION] event:" + eventType);

## Your Task:
Read the code below and add 2-5 console.log statements at the MOST IMPORTANT points:
- API endpoint handlers
- Data fetch/callback functions
- User interaction handlers
- Key state changes

Return ONLY the complete modified code - no explanations.

```javascript
{content}
```

## Modified code (with logs added):"""


# ============================================================================
# Log Injector
# ============================================================================

class SemanticLogInjector:
    """Inject semantic logs using LLM - one file at a time"""

    def __init__(self):
        self.llm = MiniMaxLLMClient()

    def inject_to_project(self, project_path: str) -> Dict:
        """
        Inject logs into all backend and frontend files.
        """
        project = Path(project_path)
        if not project.exists():
            return {"status": "error", "message": "Project not found"}

        results = {
            "project": str(project),
            "timestamp": datetime.now().isoformat(),
            "files_processed": 0,
            "files_modified": 0,
            "errors": [],
        }

        # Collect files to process
        files_to_process = []

        backend_dir = project / "backend"
        if backend_dir.exists():
            for f in backend_dir.rglob("*.js"):
                if "node_modules" not in str(f):
                    files_to_process.append(f)

        frontend_dir = project / "frontend"
        if frontend_dir.exists():
            for ext in ["*.jsx", "*.js", "*.tsx"]:
                for f in frontend_dir.rglob(ext):
                    if "node_modules" not in str(f):
                        files_to_process.append(f)

        print(f"Found {len(files_to_process)} files to process")

        for file_path in files_to_process:
            print(f"  Processing: {file_path.relative_to(project)}")

            try:
                content = file_path.read_text()

                # Call LLM to get modified content
                modified = self.llm.inject_logs(file_path, content)

                if modified and modified != content:
                    # Extract code from markdown if present
                    modified = self._extract_code(modified)

                    file_path.write_text(modified)
                    results["files_modified"] += 1
                    print(f"    Modified: {file_path.relative_to(project)}")
                else:
                    print(f"    No changes needed")

                results["files_processed"] += 1

            except Exception as e:
                error_msg = f"Error processing {file_path}: {str(e)}"
                results["errors"].append(error_msg)
                print(f"    ERROR: {e}")

        results["status"] = "completed"
        return results

    def _extract_code(self, text: str) -> str:
        """Extract code from markdown code block if present"""
        # Try to find code block
        if "```javascript" in text:
            start = text.find("```javascript") + len("```javascript")
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        if "```" in text:
            start = text.find("```") + len("```")
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        # If no code block, return as-is
        return text.strip()


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-based Semantic Log Injector")
    parser.add_argument("--project", required=True, help="Path to project directory")
    parser.add_argument("--output", help="Output file for results (optional)")

    args = parser.parse_args()

    print(f"Starting log injection for: {args.project}")
    print("=" * 60)

    injector = SemanticLogInjector()
    results = injector.inject_to_project(args.project)

    print("=" * 60)
    print(f"Completed!")
    print(f"  Files processed: {results['files_processed']}")
    print(f"  Files modified: {results['files_modified']}")
    print(f"  Errors: {len(results['errors'])}")

    if results['errors']:
        print("\nErrors:")
        for err in results['errors']:
            print(f"  - {err}")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")