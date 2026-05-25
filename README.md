# TeleGen: Observable Repair for LLM-Generated Web Applications

TeleGen is an observability-enhanced framework for improving LLM-generated web applications by collecting runtime telemetry during task execution and using it to guide code repair.

## Overview

LLM-generated web applications often look plausible but fail interactive workflows because of hidden issues such as broken navigation, missing event handlers, frontend-backend contract mismatches, runtime errors, or state updates that are not reflected in the UI. Standard task feedback only reports whether a task passed or failed, but often does not explain what happened during execution. TeleGen addresses this by making the generated application observable before repair.

TeleGen augments existing web code-generation pipelines with a runtime telemetry loop: after an initial application is generated, TeleGen instruments a separate copy of the application, re-runs the task executor, collects runtime telemetry, compresses the raw logs into a telemetry brief, and provides this brief to a repair agent.

## Pipeline

1. **Initial Generation**: A coding agent generates a v1 web application from a website specification and UI task suite. TeleGen augments existing generation pipelines rather than replacing their original generation or execution protocols.
2. **Runtime Telemetry Collection**: TeleGen creates an instrumented copy of the v1 application while preserving the clean v1 source code for repair. An LLM-based coding agent inserts lightweight telemetry logs at locations likely to help diagnose task failures. The instrumentation step is only for observation; it should not change the application behavior or perform repair. The task executor re-runs the same tasks on the instrumented application, collecting runtime telemetry such as user actions, network behavior, errors, and state changes.
3. **Telemetry Brief Construction**: Raw telemetry logs can be long, noisy, and repetitive. TeleGen uses a compression agent to combine task context with the collected logs and produce a compact telemetry brief. The telemetry brief is not a full execution transcript — it is a repair-oriented summary of what happened during task execution.
4. **Telemetry-Guided Repair**: The repair agent receives clean v1 source code, task feedback, and the telemetry brief. The repair agent edits the clean v1 source code (not the instrumented copy), producing a revised v2 application.
5. **Re-evaluation**: The task executor re-runs the same task suite on the v2 application. The final result measures whether runtime telemetry helps the repaired application better satisfy the intended workflows.

## What TeleGen Collects

TeleGen collects runtime signals such as user actions, network requests and responses, runtime errors, state changes, and task-relevant execution traces. These signals help the repair agent distinguish failures that look similar from final task outcomes alone.

## Why Separate Instrumentation and Repair?

TeleGen instruments a separate copy of the v1 application and preserves the clean v1 source code for repair. This separation ensures that telemetry collection is used only for observation, while functional changes are made only during the repair stage.

## Architecture

```
launch_multi_docker.py          ← Entry point: launches Docker containers
    └── run_project_worker.sh   ← Worker entrypoint inside container
        └── run_full_pipeline_llm_injection.sh  ← Main orchestration
            ├── Phase 1: run_batch.py
            │   ├── 1a. OpenHands code generation (DeepSeek-V4)
            │   ├── 1b. LLM telemetry injection
            │   └── 1c. WebVoyager v1 test + log collection
            ├── Phase 2: optimize_batch_results.py
            │   ├── 2a. Telemetry brief compression (LLM)
            │   ├── 2b. OpenHands observable repair
            │   └── 2c. WebVoyager v2 test + quality gate
            └── Phase 3: WebVoyager auto-evaluation (Qwen3.5-Plus)
```

## Core Modules

| File | Role |
|---|---|
| `launch_multi_docker.py` | Multi-Docker container parallel launcher |
| `run_project_worker.sh` | Container worker entrypoint |
| `run_full_pipeline_llm_injection.sh` | Full pipeline orchestration |
| `run_batch.py` | Phase 1: generation + injection + WV1 test |
| `optimize_batch_results.py` | Phase 2: brief + repair + WV2 + quality gate |
| `dynamic_repair_pipeline.py` | Core pipeline library (Phase 0-3 steps) |
| `llm_log_injector.py` | LLM telemetry injector (DeepSeek API) |
| `llm_telemetry_extractor.py` | LLM log analysis & compression |
| `telemetry_sanitizer.py` | Log sanitization & Markdown report |
| `webvoyager_eval.py` | WebVoyager task auto-evaluation |
| `run_phase3_parallel.py` | Phase 3 parallel executor |
| `model_config.py` | Model config & routing |
| `experiment_metadata.py` | Experiment metadata |

## Prompt Templates

| File | Use |
|---|---|
| `prompts/evidence_based_optimization_prompt.txt` | Observable repair (with telemetry brief) |
| `prompts/no_log_baseline_repair_prompt.txt` | No-telemetry baseline repair |
| `prompts/raw_logs_repair_prompt.txt` | Raw-log repair (ablation) |

## Quick Start

### 1. Setup

```bash
pip install openhands
cp .env.example .env
# Edit .env with your DEEPSEEK_API_KEY and QWEN_API_KEY
# Build Docker image (first time only)
python openhands_integration/launch_multi_docker.py --build
```

### 2. Run main experiment (LLM injection)

```bash
# Single project
python openhands_integration/launch_multi_docker.py \
  --projects 000001 --workers 1

# Batch (projects 000001-000010)
python openhands_integration/launch_multi_docker.py \
  --start 000001 --end 000010 --workers 4
```

### 3. Run ablations

```bash
# Raw-logs ablation (no LLM brief, repair from raw telemetry)
python openhands_integration/launch_multi_docker.py \
  --start 000001 --end 000010 \
  --raw-logs --only-repair --workers 4
```

### 4. CLI Reference

| Flag | Type | Description |
|---|---|---|
| `--projects` | str | Comma-separated project IDs |
| `--start / --end` | str | Project range (e.g. 000001-000101) |
| `--workers` | int | Max parallel containers (default 2) |
| `--model` | str | Unified model name |
| `--raw-logs` | flag | Ablation: skip LLM brief, use raw telemetry |
| `--only-repair` | flag | Repair-only: skip v1 gen+injection+WV1 |
| `--skip-existing` | flag | Skip completed projects |
| `--container-cli` | str | Container CLI (docker/podman) |
| `--build` | flag | Build Docker image before launch |
| `--webvoyager-workers` | int | WebVoyager workers per project (default 2) |

## Environment Variables

| Variable | Description |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key (code generation/repair) |
| `DEEPSEEK_MODEL` | DeepSeek model (default deepseek-v4-flash) |
| `QWEN_API_KEY` | Qwen API key (WebVoyager browser agent) |
| `QWEN_MODEL` | Qwen model (default qwen3.5-plus) |
| `CONTAINER_CLI` | Container CLI (default docker) |
| `WEBVOYAGER_NUM_WORKERS` | Internal WebVoyager parallelism |

## Experiment Data

All data under `batch_runs/official/`. See `EXPERIMENT_MANIFEST.json` for details.

| Experiment | Model | Description |
|---|---|---|
| `flash_llm_injection_analysis/` + `flash_llm_injection_data/` | Flash | Main experiment (101 projects, 647 tasks) |
| `flash_raw_logs_ablation/` | Flash | Ablation: raw-log repair |
| `pro_llm_injection/` | Pro | Main experiment (96 projects, 610 tasks) |
| `pro_raw_logs_ablation/` | Pro | Ablation: raw-log repair |
| `analysis_trace_vs_no_log/` | — | Auxiliary analysis |

Paper statistics under `batch_runs/paper_materials/output/`.

## Directory Structure

```
TeleGen/
├── README.md                    ← This file
├── .env                         ← API keys (git-ignored)
├── data/test.jsonl              ← WebGen-Bench test data
├── docker/                      ← Docker build files
├── webvoyager/                  ← WebVoyager browser agent
├── batch_runs/
│   ├── official/                ← Official experiment data
│   └── paper_materials/         ← Paper statistics & appendix
└── openhands_integration/       ← Core pipeline code
    ├── launch_multi_docker.py
    ├── run_batch.py
    ├── optimize_batch_results.py
    ├── dynamic_repair_pipeline.py
    ├── prompts/                 ← Prompt templates
    └── ...
```
