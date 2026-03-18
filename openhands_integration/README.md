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
