#!/usr/bin/env bash
# Phase 2 only worker: runs logged + no-log repair for one project.
set -euo pipefail
PROJECT_ID=""
WORKSPACE="${WORKSPACE:-$(pwd)}"
RUN_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --run-dir) RUN_ROOT="$2"; shift 2 ;;
    --model) shift 2 ;;
    --reuse-openhands-workspace) shift ;;
    *) shift ;;
  esac
done
[[ -z "$PROJECT_ID" ]] && { echo "ERROR: --project-id required"; exit 2; }
WORKSPACE="$(cd "$WORKSPACE" && pwd)"

export HOME="${TELEGEN_WORKER_HOME:-/tmp/telegen-home}"
mkdir -p "$HOME"
export WEBVOYAGER_NUM_WORKERS="${WEBVOYAGER_NUM_WORKERS:-2}"
export PIPELINE_WEB_STACK_LOCK="${PIPELINE_WEB_STACK_LOCK:-/tmp/telegen_web_stack_${PROJECT_ID}.lock}"

# run-dir = per-project dir
RUN_DIR="${RUN_ROOT:-$WORKSPACE/batch_runs/official/gemini31_pro_full/project_${PROJECT_ID}}"
echo "[phase2-worker:$PROJECT_ID] run_dir=$RUN_DIR"

cd "$WORKSPACE"
EVIDENCE_PROMPT="$WORKSPACE/openhands_integration/prompts/evidence_based_optimization_prompt.txt"
NO_LOG_PROMPT="$WORKSPACE/openhands_integration/prompts/no_log_baseline_repair_prompt.txt"

# Phase 2A: logged repair
echo "[phase2-worker:$PROJECT_ID] === Phase 2A: logged repair ==="
python3 -u openhands_integration/optimize_batch_results.py \
  --run-dir "$RUN_DIR" \
  --start "$PROJECT_ID" --end "$PROJECT_ID" \
  --source-variant llm --branch-name logged \
  --summary-file "$RUN_DIR/dynamic_repair_logged_summary.json" \
  --prompt-template "$EVIDENCE_PROMPT" \
  --timeout 5400 --webvoyager-timeout 1800 --webvoyager-max-iter 10 \
  --repair-rounds 1 || echo "[phase2-worker:$PROJECT_ID] Phase 2A failed"

# Phase 2B: no-log baseline
echo "[phase2-worker:$PROJECT_ID] === Phase 2B: no-log baseline ==="
python3 -u openhands_integration/optimize_batch_results.py \
  --run-dir "$RUN_DIR" \
  --start "$PROJECT_ID" --end "$PROJECT_ID" \
  --source-variant clean --branch-name no_log \
  --summary-file "$RUN_DIR/dynamic_repair_no_log_summary.json" \
  --skip-telemetry-report --skip-llm-brief \
  --prompt-template "$NO_LOG_PROMPT" \
  --timeout 5400 --webvoyager-timeout 1800 --webvoyager-max-iter 10 \
  --repair-rounds 1 || echo "[phase2-worker:$PROJECT_ID] Phase 2B failed"

echo "[phase2-worker:$PROJECT_ID] DONE"
