#!/usr/bin/env bash
set -euo pipefail

# Custom worker: re-run only Phase3 (WebVoyager v2) for the logged branch.
# Skips Phase1 (telemetry), Phase1-brief (LLM extraction), and Phase2 (OpenHands repair).
# Phase0 (freeze source) still runs to ensure a clean experiment workspace copy.

PROJECT_ID=""
WORKSPACE="${WORKSPACE:-$(pwd)}"
RUN_ROOT=""
RUN_DIR=""
MODEL_NAME="${MODEL_NAME:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --run-root) RUN_ROOT="$2"; shift 2 ;;
    --run-dir) RUN_DIR="$2"; shift 2 ;;
    --model) MODEL_NAME="$2"; shift 2 ;;
    --reuse-openhands-workspace) shift ;;
    *) shift ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: --project-id is required" >&2
  exit 2
fi

WORKSPACE="$(cd "$WORKSPACE" && pwd)"
if [[ -z "$RUN_ROOT" ]]; then
  RUN_ROOT="$WORKSPACE/batch_runs/multi_docker_manual"
fi
if [[ -z "$RUN_DIR" ]]; then
  RUN_DIR="$RUN_ROOT/project_${PROJECT_ID}"
fi

mkdir -p "$RUN_DIR"
cd "$WORKSPACE"

export HOME="${TELEGEN_WORKER_HOME:-/tmp/telegen-home}"
mkdir -p "$HOME"
git config --global user.email "telegen-worker@example.local"
git config --global user.name "TeleGen Worker"

export WEBVOYAGER_NUM_WORKERS="${WEBVOYAGER_NUM_WORKERS:-2}"
export PIPELINE_WEB_STACK_LOCK="${PIPELINE_WEB_STACK_LOCK:-/tmp/telegen_web_stack_${PROJECT_ID}.lock}"

SUMMARY_FILE="$RUN_DIR/dynamic_repair_logged_summary.json"
PROMPT_TEMPLATE="$WORKSPACE/openhands_integration/prompts/evidence_based_optimization_prompt.txt"

MODEL_ARGS=()
if [[ -n "$MODEL_NAME" ]]; then
  MODEL_ARGS=(--model "$MODEL_NAME")
fi

echo "[wv-only:$PROJECT_ID] workspace=$WORKSPACE"
echo "[wv-only:$PROJECT_ID] run_dir=$RUN_DIR"
echo "[wv-only:$PROJECT_ID] Skipping Phase1/Phase2, running only Phase3 (WebVoyager v2)"

python3 -u openhands_integration/optimize_batch_results.py \
  --run-dir "$RUN_DIR" \
  --start "$PROJECT_ID" \
  --end "$PROJECT_ID" \
  --source-variant llm \
  --branch-name logged \
  --summary-file "$SUMMARY_FILE" \
  --prompt-template "$PROMPT_TEMPLATE" \
  --timeout 5400 \
  --webvoyager-timeout 1800 \
  --webvoyager-max-iter 10 \
  --repair-rounds 1 \
  --skip-telemetry-report \
  --skip-llm-brief \
  --skip-phase2 \
  "${MODEL_ARGS[@]}"
