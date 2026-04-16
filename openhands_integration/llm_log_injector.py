"""
LLM-based Semantic Log Injector V2
==================================

Directly uses LLM API to inject semantic logs into code files.
Fast and lightweight - one API call per file with retry logic.

Improvements V2:
- Retry logic for incomplete code
- Better validation of LLM output
- Rate limiting to avoid 429 errors
- Backup before modification
- Syntax validation

Usage:
    python llm_log_injector.py --project openhands_generated/project_000002
"""

import os
import sys
import json
import argparse
import time
import shutil
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
# LLM Client with retry logic
# ============================================================================

class MiniMaxLLMClient:
    """Simple MiniMax API client for log injection with retry"""

    def __init__(self, max_retries: int = 2):
        self.api_key = os.getenv("MINIMAX_API_KEY", "")
        self.base_url = "https://api.minimaxi.com/v1"
        self.model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
        self.max_retries = max_retries

    def inject_logs(self, file_path: Path, file_content: str, is_retry: bool = False) -> Optional[str]:
        """
        Send file to LLM and get back content with semantic logs added.
        Returns the modified content or None on failure.
        """
        prompt = self._build_prompt(file_content, file_path.suffix, is_retry=is_retry)

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

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=120.0) as client:
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                    if response.status_code == 429:
                        # Rate limited - wait and retry
                        wait_time = 5 * (attempt + 1)
                        print(f"    Rate limited, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    result = response.json()
                    message = result["choices"][0]["message"]

                    # Get the raw content
                    content = message.get("content", "") or message.get("output", "") or ""

                    # Strip thinking blocks (<think>...</think>) - MiniMax embeds thinking in content
                    import re
                    content = re.sub(r'<think>[\s\S]*?</think>', '', content)

                    return content.strip()

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait_time = 5 * (attempt + 1)
                    print(f"    Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                print(f"    HTTP error: {e}")
                return None

            except Exception as e:
                print(f"    Error calling API: {e}")
                return None

        print(f"    Failed after {self.max_retries} attempts")
        return None

    def _build_prompt(self, content: str, file_ext: str, is_retry: bool = False) -> str:
        """Build prompt for log injection"""

        if file_ext in ['.jsx', '.tsx', '.js']:
            lang = "JavaScript/React"
        else:
            lang = "JavaScript"

        retry_note = "\n## IMPORTANT: Return ONLY the code. NO comments, NO explanations, NO markdown. Just pure JavaScript." if is_retry else ""

        return f"""You are adding SEMANTIC logging to existing {lang} code.

## CRITICAL RULES:
1. ONLY add console.log statements - do NOT modify any other code
2. Do NOT change business logic, algorithms, or code structure
3. Logs MUST be placed INSIDE function bodies or callback functions, NOT at module/file level
4. Return ONLY the complete modified code file - NO comments, explanations, or markdown formatting{retry_note}
5. All your reasoning and <think> blocks MUST be completely outside of the final markdown code blocks. You are strictly forbidden from placing <think> tags inside the ``` blocks. The code blocks must contain ONLY syntactically valid executable code.

## Logging Format:
- Backend API: console.log("[API] " + req.method + " " + req.path + " params:" + JSON.stringify(req.params));
- Backend data: console.log("[DATA] operation result count: " + result.length);
- Frontend render: console.log("[RENDER] ComponentName");
- Frontend API call: console.log("[API_CALL] endpoint:" + url);
- Frontend interaction: console.log("[ACTION] event:" + eventType);

## Your Task:
Read the code below and add console.log statements at the MOST IMPORTANT points:
- INSIDE route handlers (router.get, router.post, etc.)
- INSIDE controller/handler functions
- INSIDE callback functions
- INSIDE React component functions

## Examples of CORRECT log placement:
```javascript
// CORRECT - log inside handler function
router.get('/search', function(req, res) {{
    console.log("[API] " + req.method + " " + req.path + " params:" + JSON.stringify(req.params));
    stockController.searchStocks(req, res);
}});

// CORRECT - log inside controller function
function searchStocks(req, res) {{
    console.log("[API] search called");
    // ... rest of code
}}
```

## Examples of INCORRECT log placement:
```javascript
// WRONG - module level, req doesn't exist here
console.log("[API] " + req.method + " " + req.path);
router.get('/search', handler);
```

## Output Format:
Return ONLY the complete JavaScript code. Start with the first line of actual code. Do NOT include any comments, explanations, or analysis. Do NOT wrap in markdown.

Original code:
{content}

Modified code (no comments, just code):"""


# ============================================================================
# Validation helpers
# ============================================================================

def validate_js_code(code: str, original_code: str) -> bool:
    """
    Validate that the modified code is valid and complete.
    """
    # Check if essential structures are preserved
    essential_patterns = [
        'require(',
        'module.exports',
        'export ',
    ]

    # If original had imports/requires, modified should too
    if 'require(' in original_code and 'require(' not in code:
        return False

    # Check for balanced braces
    if code.count('{') != code.count('}'):
        return False

    # Check for balanced parentheses
    if code.count('(') != code.count(')'):
        return False

    # Check not empty
    if not code.strip():
        return False

    # Check minimum length (should be at least 50% of original)
    if len(code) < len(original_code) * 0.5:
        return False

    return True


def validate_js_syntax(code: str) -> bool:
    """
    Basic JavaScript syntax validation.
    Returns True if syntax appears valid.
    """
    # Check for common syntax errors
    lines = code.split('\n')

    # Track bracket balance
    brace_count = 0
    paren_count = 0
    bracket_count = 0

    for line in lines:
        # Skip comments and strings for balance check
        stripped = line.strip()

        # Skip single line comments
        if stripped.startswith('//'):
            continue

        for char in stripped:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
            elif char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
            elif char == '[':
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1

    return brace_count == 0 and paren_count == 0 and bracket_count == 0


# ============================================================================
# Log Injector
# ============================================================================

class SemanticLogInjector:
    """Inject semantic logs using LLM - one file at a time with retry"""

    def __init__(self, max_retries: int = 2):
        self.llm = MiniMaxLLMClient(max_retries=max_retries)
        self.backup_dir = None

    def inject_to_project(self, project_path: str) -> Dict:
        """
        Inject logs into all backend and frontend files.
        """
        project = Path(project_path)
        if not project.exists():
            return {"status": "error", "message": "Project not found"}

        # Create backup directory
        self.backup_dir = project / ".log_injector_backup"
        self.backup_dir.mkdir(exist_ok=True)

        results = {
            "project": str(project),
            "timestamp": datetime.now().isoformat(),
            "files_processed": 0,
            "files_modified": 0,
            "files_skipped": 0,
            "errors": [],
        }

        # Collect files to process
        files_to_process = []

        backend_dir = project / "backend"
        if backend_dir.exists():
            for f in backend_dir.rglob("*.js"):
                if "node_modules" not in str(f) and ".log_injector_backup" not in str(f):
                    files_to_process.append(f)

        frontend_dir = project / "frontend"
        if frontend_dir.exists():
            for ext in ["*.jsx", "*.js", "*.tsx"]:
                for f in frontend_dir.rglob(ext):
                    if "node_modules" not in str(f) and ".log_injector_backup" not in str(f) and "dist/" not in str(f):
                        files_to_process.append(f)

        print(f"Found {len(files_to_process)} files to process")

        for file_path in files_to_process:
            print(f"  Processing: {file_path.relative_to(project)}")

            try:
                content = file_path.read_text()

                # Backup original
                rel_path = file_path.relative_to(project)
                backup_path = self.backup_dir / rel_path
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, backup_path)

                # Call LLM to get modified content
                modified = self.llm.inject_logs(file_path, content)

                if not modified:
                    print(f"    ERROR: LLM returned nothing")
                    results["errors"].append(f"LLM failed for {file_path.name}")
                    results["files_skipped"] += 1
                    continue

                # Extract code from markdown if present
                modified = self._extract_code(modified)

                # Validate the modified code
                if not validate_js_code(modified, content):
                    print(f"    WARNING: Validation failed, attempting retry...")

                    # Retry with more explicit prompt
                    modified = self.llm.inject_logs(file_path, content, is_retry=True)
                    if modified:
                        modified = self._extract_code(modified)

                if not modified or not validate_js_code(modified, content):
                    print(f"    SKIPPED: Invalid code from LLM")
                    results["errors"].append(f"Invalid code from LLM for {file_path.name}")
                    results["files_skipped"] += 1
                    # Restore from backup
                    shutil.copy2(backup_path, file_path)
                    continue

                # Additional syntax validation
                if not validate_js_syntax(modified):
                    print(f"    WARNING: Syntax may be invalid")
                    results["errors"].append(f"Potential syntax issue in {file_path.name}")

                # Write modified content
                file_path.write_text(modified)
                results["files_modified"] += 1
                print(f"    Modified: {file_path.relative_to(project)}")

                results["files_processed"] += 1

                # Rate limiting delay
                time.sleep(1)

            except Exception as e:
                error_msg = f"Error processing {file_path}: {str(e)}"
                results["errors"].append(error_msg)
                print(f"    ERROR: {e}")

        results["status"] = "completed"
        return results

    def _extract_code(self, text: str) -> str:
        """
        Extract code from various formats:
        1. Markdown code blocks (```javascript, ```js, ```)
        2. Plain text with prompt/thinking content before actual code
        3. Plain text with explanation after code
        """
        if not text:
            return ""

        original_text = text
        text = text.strip()

        # Method 1: Try markdown code blocks
        if "```javascript" in text:
            start = text.find("```javascript") + len("```javascript")
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        if "```js" in text:
            start = text.find("```js") + len("```js")
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        if "```" in text:
            # Find the first ``` after an actual code start indicator
            first_triple = text.find("```")
            if first_triple > 0:
                # Check if it looks like a code block (followed by actual code)
                after_first = text[first_triple + 3:].strip()
                if after_first and self._looks_like_code(after_first[:100]):
                    # This is a code block - extract from after it to the next ```
                    start = first_triple + 3
                    end = text.find("```", start)
                    if end > start:
                        code = text[start:end].strip()
                        if self._looks_like_code(code[:50]):
                            return code

        # Method 2: No code block found - find where actual code starts
        # Common code start patterns
        code_start_indicators = [
            # React/JS component patterns
            r'^function\s+\w+',
            r'^const\s+\w+\s*=',
            r'^let\s+\w+\s*=',
            r'^var\s+\w+\s*=',
            r'^export\s+',
            r'^import\s+',
            r'^class\s+\w+',
            r'^if\s*\(',
            r'^for\s*\(',
            r'^while\s*\(',
            r'^return\s+',
            r'^router\.',
            r'^app\.',
            r'^server\.',
            # Express route patterns
            r'^router\.(get|post|put|delete|patch|use)',
            r'^module\.exports',
            # Arrow functions at start
            r'^\(\s*\)\s*=>',
            r'^\w+\s*=>',
        ]

        lines = text.split('\n')

        # Find the first line that looks like actual code
        code_start_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            # Skip obvious non-code lines
            if self._is_likely_prompt_text(stripped):
                continue

            # Check if this line looks like code
            if self._looks_like_code(stripped):
                # Make sure it's not in the middle of a prompt/explanation
                # by checking previous lines aren't all explanatory
                code_start_idx = i
                break

        if code_start_idx >= 0:
            # Extract from code start to end (but strip trailing non-code)
            code_lines = lines[code_start_idx:]

            # Find where code ends - look for trailing explanations
            code_end_idx = len(code_lines)
            for i in range(len(code_lines) - 1, -1, -1):
                line = code_lines[i].strip()
                if not line:
                    continue
                # If last few lines are explanations (short, no brackets), cut them
                if self._is_likely_explanation(line) and i > len(code_lines) - 3:
                    code_end_idx = i
                else:
                    break

            result = '\n'.join(code_lines[:code_end_idx]).strip()
            if result:
                return result

        # Fallback: return original stripped
        return original_text.strip()

    def _looks_like_code(self, text: str) -> bool:
        """Check if text looks like actual code (not prompt/explanation)"""
        if not text:
            return False

        text = text.strip()

        # Very short lines are likely not code
        if len(text) < 3:
            return False

        # Skip lines that are clearly explanations or prompts
        if self._is_likely_prompt_text(text):
            return False

        # Code typically contains these patterns
        code_indicators = [
            '{', '}', '(', ')', ';', '=>', 'function', 'const', 'let', 'var',
            'return', 'if', 'else', 'for', 'while', 'class', 'import', 'export',
            'require(', 'module.exports', 'router', 'app.', 'async', 'await',
            'console.log', 'console.error', 'console.warn',
            'export default', 'export const', 'export function',
            'import ', 'from ',
        ]

        for indicator in code_indicators:
            if indicator in text:
                return True

        return False

    def _is_likely_prompt_text(self, text: str) -> bool:
        """Check if text is likely prompt/instruction text rather than code"""
        if not text:
            return True

        text_lower = text.lower()

        # Common prompt/thinking phrases
        prompt_phrases = [
            # Direct prompt instructions
            'the user wants me to',
            'the user asks',
            'the user says',
            'the user says to',
            'i need to add',
            'i should add',
            'let me add',
            'i will add',
            'i could add',
            'here is the modified',
            'here is the code',
            "here's the modified",
            "here's the code",
            'the modified code',
            'the code below',
            'the original code',
            'modified code',
            'return only',
            'do not modify',
            'do not change',
            'add console.log',
            'add 2-5 console.log',
            'no comments',
            'no explanations',
            'no markdown',
            'important:',
            'note:',
            'note that',
            'note,',
            'note-',
            # Analysis/thinking patterns (common in LLM responses)
            'looking at the',
            'looking at this',
            'looking more carefully',
            'the instructions say',
            'the user says to add',
            'the user might want',
            'the user might be',
            'this function',
            'this component',
            'this code',
            'this logic',
            'this is a',
            'this would',
            'the following',
            'as shown',
            'for example',
            'in this case',
            'when the user',
            'the instruction',
            'your task is',
            'your code is',
            'you are a',
            "i'm a",
            # Bullet/number list patterns (common in prompts)
            '1. only add',
            '2. do not',
            '3. logs must',
            '4. return only',
            '- `console.log',
            '- the main',
            '- formatcurrency',
            '- gettrendclass',
            '- getratingclass',
            '- the component',
            # Lines starting with common explanation words
            'which logs',
            'to log',
            'as a result',
            'therefore',
            'however',
            'but the',
            'since the',
            'although the',
            'wait, the',
            'seems to',
            "i've already",
            'the existing',
            'already have',
            'the current',
        ]

        # Check if line starts with (not just contains) a prompt phrase
        for phrase in prompt_phrases:
            if text_lower.startswith(phrase):
                return True

        # Skip lines that are mostly these phrases
        if len(text) < 50:
            count = sum(1 for phrase in prompt_phrases if phrase in text_lower)
            if count >= 2:
                return True

        return False

    def _is_likely_explanation(self, text: str) -> bool:
        """Check if text is likely an explanation (trailing text after code)"""
        if not text:
            return True

        text_lower = text.lower()

        # Common explanation phrases
        explanation_phrases = [
            'the code above',
            'this adds',
            'this logs',
            'which logs',
            'to log',
            'as a result',
            'therefore',
            'however',
            'note:',
            'note that',
            'important:',
        ]

        for phrase in explanation_phrases:
            if phrase in text_lower:
                return True

        # Short lines without brackets or semicolons are likely explanations
        has_code_chars = any(c in text for c in ['{', '}', ';', '(', ')', '='])
        if not has_code_chars and len(text) < 80:
            return True

        return False


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-based Semantic Log Injector V2")
    parser.add_argument("--project", required=True, help="Path to project directory")
    parser.add_argument("--output", help="Output file for results (optional)")

    args = parser.parse_args()

    print(f"Starting log injection for: {args.project}")
    print("=" * 60)

    injector = SemanticLogInjector(max_retries=2)
    results = injector.inject_to_project(args.project)

    print("=" * 60)
    print(f"Completed!")
    print(f"  Files processed: {results['files_processed']}")
    print(f"  Files modified: {results['files_modified']}")
    print(f"  Files skipped: {results['files_skipped']}")
    print(f"  Errors: {len(results['errors'])}")

    if results['errors']:
        print("\nErrors:")
        for err in results['errors']:
            print(f"  - {err}")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")
