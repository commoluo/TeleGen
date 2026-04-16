# OpenHands Integration Configuration

## Environment Variables

Set these before running the integration:

```bash
# LLM Configuration
export LLM_API_KEY="your-api-key"
export LLM_MODEL="anthropic/claude-sonnet-4-20250514"  # or your preferred model
export LLM_BASE_URL="https://api.anthropic.com"  # or your custom endpoint

# Alternative: Use OpenAI compatible API
export LLM_MODEL="gpt-4o"
export LLM_BASE_URL="https://api.openai.com/v1"
```

## Runtime Settings

Edit `src/__init__.py` to modify:

```python
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
        "timeout": 3600,
    },
    "logging": {
        "enable_trace": True,
        "trace_dir": "./logging_traces",
        "pause_after_generation": True,
    }
}
```

## Directory Structure

```
openhands_integration/
├── src/
│   └── __init__.py      # Main integration code
├── config/
│   └── settings.yaml    # Configuration file
├── prompts/
│   └── fullstack_prompts.yaml  # Custom prompts
└── tests/
    └── test_integration.py  # Integration tests
```

## Quick Start

```python
from openhands_integration.src import (
    FullstackOpenHandsGenerator,
    LoggingInjector,
    ComparativeAnalyzer
)

# Generate project with logging
generator = FullstackOpenHandsGenerator()
result = generator.generate_project(
    project_name="my_project",
    requirements="Create a stock lookup app...",
    inject_logging=True
)
```

## Next Steps

1. Configure LLM credentials
2. Run test generation
3. Analyze trace outputs
4. Compare logged vs non-logged experiments

## Dynamic Telemetry-Driven Repair SOP

This repository now includes an executable SOP pipeline matching:

OpenHands (initial generation) -> AST probe injection -> OpenClaw/WebVoyager testing -> telemetry sanitization -> OpenHands evidence-based repair.

### Files

- `dynamic_repair_pipeline.py`: end-to-end orchestrator for Phase 0, 1, and 2.
- `telemetry_sanitizer.py`: allowlist filtering, temporal debouncing, JSON unpacking, and dimensionality reduction.
- `llm_telemetry_extractor.py`: LLM-based extraction that compresses frontend console logs into a strict timeline/error brief.
- `prompts/evidence_based_optimization_prompt.txt`: strict optimization prompt template.

### Run

```bash
python openhands_integration/dynamic_repair_pipeline.py \
    --source-workspace batch_runs/run_20260324_205358/gen_000001/project_000001 \
    --webvoyager-results batch_runs/run_20260324_205358/webvoyager_results/000001 \
    --max-iterations 12
```

### Outputs

- `*_v2_experiment/`: isolated and frozen experiment workspace.
- `*_v2_experiment/.git`: baseline git history with `Initial generation` commit.
- `*_v2_experiment/telemetry_report.md`: sanitized evidence artifact.
- `*_v2_experiment/openhands_repair_task.txt`: Phase 2 task payload.
- `*_v2_experiment/openhands_repair_stdout.log` and `openhands_repair_stderr.log`: OpenHands execution logs.
- `*_v2_experiment/dynamic_repair_summary.json`: machine-readable phase summary.

### Optional: LLM Log Extraction

Use this when `telemetry_report.md` is too long for the optimization model context window.

```bash
python openhands_integration/llm_telemetry_extractor.py \
    --input batch_runs/run_20260324_205358/webvoyager_results/000034 \
    --output batch_runs/run_20260324_205358/gen_000034/project_000034_v2_experiment/telemetry_brief.md
```
