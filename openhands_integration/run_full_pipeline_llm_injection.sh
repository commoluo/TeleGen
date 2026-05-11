#!/bin/bash
# Full pipeline for projects using LLM-based log injection.
# Default mode is per-project sequential execution:
#   000001: v1 generate + inject + WV1 -> v2 repair + WV2 -> report
#   000002: v1 generate + inject + WV1 -> v2 repair + WV2 -> report
# This avoids waiting for the whole batch to finish Phase 1 before starting Phase 2.
#
# Usage:
#   bash openhands_integration/run_full_pipeline_llm_injection.sh
#   bash openhands_integration/run_full_pipeline_llm_injection.sh --only-optimize batch_runs/run_YYYYMMDD_XXXXXX
#   bash openhands_integration/run_full_pipeline_llm_injection.sh --start 000060
#   bash openhands_integration/run_full_pipeline_llm_injection.sh --start 000001 --end 000003 --model qwen3.5-plus
#   bash openhands_integration/run_full_pipeline_llm_injection.sh --batch-mode
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$WORKSPACE/batch_runs/pipeline_logs"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
PIPELINE_LOG="$LOG_DIR/pipeline_llm_inject_${TIMESTAMP}.log"

# Args
START_ID="${START_ID:-000044}"
END_ID="${END_ID:-000101}"
ONLY_OPTIMIZE=""
MODEL_NAME="${MODEL_NAME:-}"
BATCH_MODE="false"
REUSE_OPENHANDS_WORKSPACE="true"
RUN_DIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --only-optimize)
      ONLY_OPTIMIZE="$2"
      shift 2
      ;;
    --start)
      START_ID="$2"
      shift 2
      ;;
    --end)
      END_ID="$2"
      shift 2
      ;;
    --model)
      MODEL_NAME="$2"
      shift 2
      ;;
    --batch-mode)
      BATCH_MODE="true"
      shift
      ;;
    --run-dir)
      RUN_DIR_OVERRIDE="$2"
      shift 2
      ;;
    --no-reuse-openhands-workspace)
      REUSE_OPENHANDS_WORKSPACE="false"
      shift
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

# Logging
exec > >(tee -a "$PIPELINE_LOG") 2>&1
echo "=================================================="
echo "Full Pipeline (LLM Injection): $START_ID -> $END_ID"
echo "Workspace: $WORKSPACE"
echo "Log: $PIPELINE_LOG"
echo "Mode: $( [[ "$BATCH_MODE" == "true" ]] && echo "batch" || echo "per-project sequential" )"
if [[ -n "$MODEL_NAME" ]]; then
  echo "Unified model: $MODEL_NAME"
fi
echo "Started: $(date)"
echo "=================================================="

cd "$WORKSPACE"

# Clear proxy env vars that interfere with API calls
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy 2>/dev/null || true

MODEL_ARGS=()
if [[ -n "$MODEL_NAME" ]]; then
  MODEL_ARGS=(--model "$MODEL_NAME")
fi

RUN_BATCH_ARGS=()
if [[ "$REUSE_OPENHANDS_WORKSPACE" == "false" ]]; then
  RUN_BATCH_ARGS=(--no-reuse-openhands-workspace)
fi

assert_phase1_success() {
  local project_id="$1"
  local run_dir="$2"
  local result_file="$run_dir/batch_results.json"

  python3 - "$result_file" "$project_id" <<'PY'
import json
import pathlib
import sys

result_file = pathlib.Path(sys.argv[1])
project_id = sys.argv[2]

if not result_file.exists():
  print(f"ERROR: Missing Phase 1 results file: {result_file}")
  sys.exit(1)

try:
  payload = json.loads(result_file.read_text(encoding="utf-8"))
except Exception as exc:
  print(f"ERROR: Failed to parse Phase 1 results file {result_file}: {exc}")
  sys.exit(1)

project = next(
  (
    item
    for item in payload.get("projects", [])
    if str(item.get("project_id", "")).zfill(6) == project_id
  ),
  None,
)
if project is None:
  print(f"ERROR: Phase 1 results missing project {project_id} in {result_file}")
  sys.exit(1)

status = str(project.get("status", "")).lower()
generation = str(project.get("generation_status", "")).lower()
injection = str(project.get("log_injection_status", "")).lower()
webvoyager = str(project.get("webvoyager_status", "")).lower()

if status == "completed" and generation == "success" and injection == "completed" and webvoyager == "success":
  sys.exit(0)

print(
  "ERROR: Phase 1 failed for project "
  f"{project_id}: status={status or 'missing'}, generation={generation or 'missing'}, "
  f"injection={injection or 'missing'}, webvoyager={webvoyager or 'missing'}"
)
sys.exit(1)
PY
}

assert_phase2_success() {
  local project_id="$1"
  local run_dir="$2"
  local result_file="$run_dir/dynamic_repair_batch_summary.json"

  python3 - "$result_file" "$project_id" <<'PY'
import json
import pathlib
import sys

result_file = pathlib.Path(sys.argv[1])
project_id = sys.argv[2]

if not result_file.exists():
  print(f"ERROR: Missing Phase 2 results file: {result_file}")
  sys.exit(1)

try:
  payload = json.loads(result_file.read_text(encoding="utf-8"))
except Exception as exc:
  print(f"ERROR: Failed to parse Phase 2 results file {result_file}: {exc}")
  sys.exit(1)

project = next(
  (
    item
    for item in payload.get("projects", [])
    if str(item.get("project_id", "")).zfill(6) == project_id
  ),
  None,
)
if project is None:
  print(f"ERROR: Phase 2 results missing project {project_id} in {result_file}")
  sys.exit(1)

item_status = str(project.get("status", "")).lower()
phase2_status = str((project.get("phase2") or {}).get("status", "")).lower()
phase3_status = str((project.get("phase3") or {}).get("status", "")).lower()
bad_phase3 = {
  "failed",
  "skipped_phase2_failed",
  "no_tasks",
  "api_key_missing",
  "backend_not_accessible",
  "frontend_not_accessible",
  "frontend_npm_install_failed",
  "evaluation_failed",
}

if item_status == "completed" and phase2_status in {"success", "skipped"} and phase3_status not in bad_phase3:
  sys.exit(0)

print(
  "ERROR: Phase 2 failed for project "
  f"{project_id}: item_status={item_status or 'missing'}, "
  f"phase2={phase2_status or 'missing'}, phase3={phase3_status or 'missing'}, "
  f"error={project.get('error', '')}"
)
sys.exit(1)
PY
}

run_phase1_for_project() {
  local project_id="$1"
  local run_dir="$2"
  local expected_total="$3"
  local phase1_log="$LOG_DIR/phase1_llm_inject_${project_id}_${TIMESTAMP}.log"
  local -a phase1_cmd

  echo ""
  echo "=== [$project_id] Phase 1: Generation + LLM Log Injection + WebVoyager v1 ==="
  echo "Starting at: $(date)"

  phase1_cmd=(
    python3 -u openhands_integration/run_batch.py
    --single "$project_id"
    --run-dir "$run_dir"
    --expected-total "$expected_total"
    --injection-mode llm
  )

  if ((${#MODEL_ARGS[@]})); then
    phase1_cmd+=("${MODEL_ARGS[@]}")
  fi

  if ((${#RUN_BATCH_ARGS[@]})); then
    phase1_cmd+=("${RUN_BATCH_ARGS[@]}")
  fi

  "${phase1_cmd[@]}" 2>&1 | tee "$phase1_log"

  assert_phase1_success "$project_id" "$run_dir"

  echo "[$project_id] Phase 1 complete. Run dir: $run_dir"
  PHASE1_RUN_DIR="$run_dir"
}

run_phase2_for_project() {
  local project_id="$1"
  local run_dir="$2"
  local phase2_log="$LOG_DIR/phase2_llm_inject_${project_id}_${TIMESTAMP}.log"

  echo ""
  echo "=== [$project_id] Phase 2: OH Repair + WebVoyager v2 + Quality Gate ==="
  echo "Run dir: $run_dir"
  echo "Starting at: $(date)"

  python3 -u openhands_integration/optimize_batch_results.py \
    --run-dir "$run_dir" \
    --start "$project_id" \
    --end "$project_id" \
    --timeout 5400 \
    --webvoyager-timeout 1800 \
    --webvoyager-max-iter 10 \
    --repair-rounds 1 \
    "${MODEL_ARGS[@]}" \
    2>&1 | tee "$phase2_log"

  assert_phase2_success "$project_id" "$run_dir"

  echo "[$project_id] Phase 2 complete at: $(date)"
}

generate_report_for_project() {
  local project_id="$1"
  local run_dir="$2"
  local report_path="$run_dir/analysis_report.html"

  echo ""
  echo "=== [$project_id] Generating Analysis Report ==="

  python3 -u openhands_integration/analyze_repair_results.py \
    --run-dir "$run_dir" \
    --output "$report_path" \
    2>&1

  echo "[$project_id] Analysis report: $report_path"
}

if [[ -n "$ONLY_OPTIMIZE" ]]; then
  RUN_DIR="$ONLY_OPTIMIZE"
  echo "[Phase 1] Skipped - using existing run dir: $RUN_DIR"

  echo ""
  echo "=== Phase 2: OH Repair + WebVoyager v2 + Quality Gate ==="
  echo "Run dir: $RUN_DIR"
  echo "Starting at: $(date)"

  python3 -u openhands_integration/optimize_batch_results.py \
    --run-dir "$RUN_DIR" \
    --start "$START_ID" \
    --end "$END_ID" \
    --timeout 5400 \
    --webvoyager-timeout 1800 \
    --webvoyager-max-iter 10 \
    --repair-rounds 1 \
    "${MODEL_ARGS[@]}" \
    2>&1 | tee "$LOG_DIR/phase2_llm_inject_${TIMESTAMP}.log"

  echo ""
  echo "Phase 2 complete at: $(date)"

  echo ""
  echo "=== Generating Analysis Report ==="
  REPORT_PATH="$RUN_DIR/analysis_report.html"

  python3 -u openhands_integration/analyze_repair_results.py \
    --run-dir "$RUN_DIR" \
    --output "$REPORT_PATH" \
    2>&1

  echo ""
  echo "Analysis report: $REPORT_PATH"
elif [[ "$BATCH_MODE" == "true" ]]; then
  echo ""
  echo "=== Phase 1: Generation + LLM Log Injection + WebVoyager v1 (${START_ID} -> ${END_ID}) ==="
  echo "Starting at: $(date)"

  PHASE1_LOG="$LOG_DIR/phase1_llm_inject_${TIMESTAMP}.log"
  python3 -u openhands_integration/run_batch.py \
    --start "$START_ID" \
    --end "$END_ID" \
    --injection-mode llm \
    "${MODEL_ARGS[@]}" \
    "${RUN_BATCH_ARGS[@]}" \
    2>&1 | tee "$PHASE1_LOG"

  RUN_DIR="$(grep -m1 'Batch output:' "$PHASE1_LOG" | sed 's/.*Batch output: //' | tr -d '[:space:]')"
  if [[ -z "$RUN_DIR" ]]; then
    echo "ERROR: Could not extract run dir from Phase 1 output. Check $PHASE1_LOG"
    exit 1
  fi

  echo ""
  echo "Phase 1 complete. Run dir: $RUN_DIR"
  echo "Phase 1 ended at: $(date)"

  echo ""
  echo "=== Phase 2: OH Repair + WebVoyager v2 + Quality Gate ==="
  echo "Run dir: $RUN_DIR"
  echo "Starting at: $(date)"

  python3 -u openhands_integration/optimize_batch_results.py \
    --run-dir "$RUN_DIR" \
    --start "$START_ID" \
    --end "$END_ID" \
    --timeout 5400 \
    --webvoyager-timeout 1800 \
    --webvoyager-max-iter 10 \
    --repair-rounds 1 \
    "${MODEL_ARGS[@]}" \
    2>&1 | tee "$LOG_DIR/phase2_llm_inject_${TIMESTAMP}.log"

  echo ""
  echo "Phase 2 complete at: $(date)"

  echo ""
  echo "=== Generating Analysis Report ==="
  REPORT_PATH="$RUN_DIR/analysis_report.html"

  python3 -u openhands_integration/analyze_repair_results.py \
    --run-dir "$RUN_DIR" \
    --output "$REPORT_PATH" \
    2>&1

  echo ""
  echo "Analysis report: $REPORT_PATH"
else
  START_DEC=$((10#$START_ID))
  END_DEC=$((10#$END_ID))
  TOTAL_PROJECTS=$((END_DEC - START_DEC + 1))
  RUN_DIR="${RUN_DIR_OVERRIDE:-$WORKSPACE/batch_runs/run_${TIMESTAMP}}"
  mkdir -p "$RUN_DIR"
  MANIFEST_PATH="$LOG_DIR/per_project_runs_${TIMESTAMP}.txt"
  : > "$MANIFEST_PATH"

  for current_dec in $(seq "$START_DEC" "$END_DEC"); do
    PROJECT_ID="$(printf '%06d' "$current_dec")"
    if ! run_phase1_for_project "$PROJECT_ID" "$RUN_DIR" "$TOTAL_PROJECTS"; then
      echo "[$PROJECT_ID] Phase 1 failed; skipping remaining stages for this project and continuing."
      printf '%s\t%s\t%s\n' "$PROJECT_ID" "$RUN_DIR" "phase1_failed" >> "$MANIFEST_PATH"
      continue
    fi
    if ! run_phase2_for_project "$PROJECT_ID" "$RUN_DIR"; then
      echo "[$PROJECT_ID] Phase 2 failed; skipping report generation for this project and continuing."
      printf '%s\t%s\t%s\n' "$PROJECT_ID" "$RUN_DIR" "phase2_failed" >> "$MANIFEST_PATH"
      continue
    fi
    generate_report_for_project "$PROJECT_ID" "$RUN_DIR"
    printf '%s\t%s\t%s\n' "$PROJECT_ID" "$RUN_DIR" "completed" >> "$MANIFEST_PATH"
  done

  echo ""
  echo "Per-project manifest: $MANIFEST_PATH"
fi

echo ""
echo "=================================================="
echo "Pipeline (LLM Injection) complete at: $(date)"
if [[ -n "${RUN_DIR:-}" ]]; then
  echo "Last run dir: $RUN_DIR"
fi
if [[ -n "${REPORT_PATH:-}" ]]; then
  echo "Last report:  $REPORT_PATH"
fi
if [[ -n "${MANIFEST_PATH:-}" ]]; then
  echo "Manifest:     $MANIFEST_PATH"
fi
echo "Full log:   $PIPELINE_LOG"
echo "=================================================="
