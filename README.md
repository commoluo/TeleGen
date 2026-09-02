# TeleGen: Improving LLM-Based Web Application Generation via Runtime Telemetry

**Findings of EMNLP 2026**

- **Code:** [https://github.com/commoluo/TeleGen](https://github.com/commoluo/TeleGen)

> A publication link will be added here once the camera-ready version is available.

## Overview

LLM-generated interactive web applications often appear plausible but fail during actual use. A workflow can break anywhere between a browser action and the final UI state — through missing event handlers, broken navigation, frontend–backend contract mismatches, runtime errors, or state updates that are never reflected in the interface. Standard generate–execute–repair pipelines hand the repair agent only task outcomes, browser feedback, or error messages: signals that reveal a workflow failed, but not the hidden execution path behind the failure.

TeleGen adds runtime observability before repair. Given a generated application, TeleGen instruments a separate copy of it, re-runs the task executor to collect runtime telemetry, distills the raw evidence into a compact telemetry brief, and provides this brief to a repair agent that edits the clean, non-instrumented source code.

```text
Generated App
    ↓
Telemetry Instrumentation
    ↓
Runtime Execution & Evidence Collection
    ↓
Telemetry Brief
    ↓
Evidence-Guided Repair
    ↓
Repaired App
```

The runtime evidence can include task-relevant signals such as user interactions and event-handler execution, navigation behavior, network requests and responses, runtime errors, application state changes, and frontend–backend coordination. Instrumentation is intended for observation only; functional changes are made on the clean source code during the repair stage.

## Main Results

| Benchmark    | Setting                 |    Result |
| ------------ | ----------------------- | --------: |
| WebGen-Bench | Initial generation      |     61.7% |
| WebGen-Bench | No-Telemetry repair     |     67.7% |
| WebGen-Bench | **TeleGen**             | **76.2%** |
| Web-Bench    | Pass@1                  |     14.2% |
| Web-Bench    | Original Pass@2         |     21.7% |
| Web-Bench    | **TeleGen Pass@2**      | **29.8%** |

**TeleGen improves task success from 67.7% to 76.2% over matched No-Telemetry repair (+8.5 percentage points).**

Reported numbers follow the paper. The WebGen-Bench results are for DeepSeek-V4-Flash on 101 projects / 647 tasks; the paper additionally evaluates DeepSeek-V4-Pro, Qwen3.5-Plus, and Gemini-3-Flash-Preview, and reports token/cost overhead, failure-category, and human-validation analyses. The reported metrics measure success on the evaluated benchmark workflows.

## Repository Structure

```
.
├── README.md
├── .env.example                      # Template for API keys
├── data/
│   └── test.jsonl                    # WebGen-Bench test set (101 projects, 647 tasks)
├── docker/
│   ├── pipeline.Dockerfile           # Pipeline image (OpenHands, Chromium, Node.js)
│   └── openhands-constraints.txt
├── openhands_integration/
│   ├── launch_multi_docker.py        # Entry point: parallel container launch / image build
│   ├── run_project_worker.sh         # Container worker entry point
│   ├── run_full_pipeline_llm_injection.sh  # End-to-end orchestration (Phases 1–3)
│   ├── run_batch.py                  # Phase 1: generation + telemetry instrumentation + WebVoyager v1
│   ├── optimize_batch_results.py     # Phase 2: brief construction + repair + WebVoyager v2
│   ├── run_phase3_parallel.py        # Parallel WebVoyager evaluation over existing runs
│   ├── dynamic_repair_pipeline.py    # Core pipeline library
│   ├── llm_log_injector.py           # LLM telemetry instrumentation
│   ├── llm_telemetry_extractor.py    # Telemetry collection & brief compression
│   ├── telemetry_sanitizer.py        # Log sanitization & telemetry report
│   ├── webvoyager_eval.py            # WebVoyager-style auto-evaluation helpers
│   ├── model_config.py               # Model normalization & routing
│   ├── experiment_metadata.py        # Experiment bookkeeping
│   └── prompts/                      # Repair prompt templates
└── webvoyager/                       # Vendored WebVoyager agent & evaluation code
```

## Setup

Requirements: Python 3, Docker (or Podman), and API access to the models used by the pipeline.

```bash
git clone https://github.com/commoluo/TeleGen.git
cd TeleGen

# Configure API keys
cp .env.example .env
# Edit .env: set DEEPSEEK_API_KEY (code generation / repair) and QWEN_API_KEY (WebVoyager evaluation)

# Build the pipeline image (first time only)
docker build -f docker/pipeline.Dockerfile -t telegen-pipeline:latest .
```

The pipeline image installs OpenHands, Chromium, Node.js, and the WebVoyager dependencies inside the container. The container CLI defaults to `docker`; set `CONTAINER_CLI=podman` (or pass `--container-cli podman`) to use Podman.

## Running TeleGen

`launch_multi_docker.py` is the main entry point. It launches one container per project and runs the full pipeline: v1 generation, telemetry instrumentation, WebVoyager v1 execution and log collection, telemetry brief construction, evidence-guided repair (plus a No-Telemetry baseline), and WebVoyager v2 evaluation.

```bash
# Single project
python3 openhands_integration/launch_multi_docker.py --projects 000001 --workers 1

# Batch (e.g. projects 000001–000010)
python3 openhands_integration/launch_multi_docker.py --start 000001 --end 000010 --workers 4

# Raw-Telemetry (No-Brief) ablation: repair from raw telemetry instead of an LLM brief
python3 openhands_integration/launch_multi_docker.py --start 000001 --end 000010 --raw-logs --workers 4
```

The launcher's `--build` flag builds the pipeline image before launching a run. Results are written under `batch_runs/` (default `batch_runs/multi_docker_run_<timestamp>/`).

The individual pipeline stages map to repository scripts:

| Stage | Script |
|---|---|
| 1. Prepare benchmark/application | `data/test.jsonl` (WebGen-Bench test set) |
| 2. Generate v1 application | `run_batch.py` (OpenHands, DeepSeek-V4-Flash) |
| 3. Instrument the application | `run_batch.py` (LLM telemetry injection) |
| 4. Execute tasks & collect telemetry | `run_batch.py` (WebVoyager v1) |
| 5. Construct telemetry brief | `optimize_batch_results.py` / `llm_telemetry_extractor.py` |
| 6. Repair | `optimize_batch_results.py` (evidence-guided repair; No-Telemetry baseline) |
| 7. Evaluate results | WebVoyager v2 + `webvoyager_eval.py` |

To re-run only the WebVoyager evaluation over an existing run directory:

```bash
python3 openhands_integration/run_phase3_parallel.py --run-dir batch_runs/<run_dir> --workers 4
```

## Reproducing Experiments

- **WebGen-Bench (full reproduction).** The pipeline can be run end-to-end from the project specifications in `data/test.jsonl` using the commands above. This requires external model APIs (DeepSeek for generation/repair, Qwen for the WebVoyager agent and evaluator) and Docker. Full reproduction of the 101-project / 647-task benchmark requires substantial API usage and compute.
- **Web-Bench.** The Web-Bench assets and reproduction scripts are not included in this repository. The reported Web-Bench numbers (Pass@1 14.2%, Pass@2 21.7% → 29.8%) are from the paper and cannot currently be reproduced from this repository alone.
- **Evaluation-only workflows.** `run_phase3_parallel.py` re-runs the WebVoyager evaluation over an existing run directory without re-generating or repairing applications.

## Prompts

Repair-stage prompt templates are in `openhands_integration/prompts/`:

- `evidence_based_optimization_prompt.txt` — TeleGen repair (with telemetry brief)
- `no_log_baseline_repair_prompt.txt` — No-Telemetry repair
- `raw_logs_repair_prompt.txt` — Raw-Telemetry (No-Brief) repair

The paper additionally describes prompt variants for initial generation, telemetry instrumentation, telemetry brief construction, and WebVoyager execution/evaluation; these are embedded in the pipeline code rather than shipped as standalone files.

## Citation

Temporary citation — the official camera-ready BibTeX will be added upon publication:

```bibtex
@misc{telegen2026,
  title        = {TeleGen: Improving LLM-Based Web Application Generation via Runtime Telemetry},
  author       = {Yujia Luo and Haonan Zhang and Jiasi Shen and Zishuo Ding and Weiyi Shang},
  year         = {2026},
  note         = {Findings of EMNLP 2026}
}
```

## Acknowledgments

This work is supported by the Guangdong Science and Technology Department (Internal Project No. G\_2025\_082).
