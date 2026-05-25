#!/bin/bash
# Full pipeline for projects using LLM-based log injection + observable repair.
# Default mode is per-project sequential execution:
#   000001: v1 generate + inject + WV1 -> v2 repair + WV2 -> report
#   000002: v1 generate + inject + WV1 -> v2 repair + WV2 -> report
# This avoids waiting for the whole batch to finish Phase 1 before starting Phase 2.
#
# Usage:
#   bash openhands_integration/run_full_pipeline_llm_injection.sh
#   bash openhands_integration/run_full_pipeline_llm_injection.sh --only-optimize batch_runs/run_YYYYMMDD_XXXXXX
#   bash openhands_integration/run_full_pipeline_llm_injection.sh --start 000060
#   bash openhands_integration/run_full_pipeline_llm_injection.sh --start 000001 --end 000003
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
RAW_LOGS_MODE="false"
ONLY_REPAIR_MODE="false"
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
    --run-dir)
      RUN_DIR_OVERRIDE="$2"
      shift 2
      ;;
    --no-reuse-openhands-workspace)
      REUSE_OPENHANDS_WORKSPACE="false"
      shift
      ;;
    --raw-logs)
      RAW_LOGS_MODE="true"
      shift
      ;;
    --only-repair)
      ONLY_REPAIR_MODE="true"
      shift
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

LOGGED_SOURCE_VARIANT="llm"
LOGGED_SOURCE_SUFFIX="LLM"OG_PROMPT="$WORKSPACE/openhands_integration/prompts/no_log_baseline_repair_prompt.txt"

# Logging
exec > >(tee -a "$PIPELINE_LOG") 2>&1
echo "=================================================="
echo "Full Pipeline (LLM Injection): $START_ID -> $END_ID"
echo "Workspace: $WORKSPACE"
echo "Log: $PIPELINE_LOG"
echo "Mode: $( [[ "$BATCH_MODE" == "true" ]] && echo "batch" || echo "per-project sequential" )"
if [[ "$RAW_LOGS_MODE" == "true" ]]; then
  echo "Repair mode: raw-logs (no LLM brief, raw telemetry_report.md)"
fi
if [[ "$ONLY_REPAIR_MODE" == "true" ]]; then
  echo "Repair-only mode: skipping Phase 1 (v1 generation + injection + WV1)"
fi
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

if status == "completed" and generation == "success" and injection in {"completed", "success", "partial_success"} and webvoyager == "success":
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
  local result_file="${3:-$run_dir/dynamic_repair_batch_summary.json}"

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
  )

  if ((${#MODEL_ARGS[@]})); then
    phase1_cmd+=("${MODEL_ARGS[@]}")
  fi

  if ((${#RUN_BATCH_ARGS[@]})); then
    phase1_cmd+=("${RUN_BATCH_ARGS[@]}")
  fi

  "${phase1_cmd[@]}" 2>&1 | tee "$phase1_log"

  assert_phase1_success "$project_id" "$run_dir" || return 1

  echo "[$project_id] Phase 1 complete. Run dir: $run_dir"
  PHASE1_RUN_DIR="$run_dir"
}

run_phase2_logged_for_project() {
  local project_id="$1"
  local run_dir="$2"
  local summary_file="$run_dir/dynamic_repair_logged_summary.json"
  local phase2_log="$LOG_DIR/phase2_logged_${project_id}_${TIMESTAMP}.log"
  local prompt_template="$EVIDENCE_PROMPT"
  local -a extra_args=()

  if [[ "$RAW_LOGS_MODE" == "true" ]]; then
    prompt_template="$RAW_LOGS_PROMPT"
    extra_args=(--skip-llm-brief)
    echo ""
    echo "=== [$project_id] Phase 2A: Raw-Logs OH Repair (no brief) + WebVoyager v2 ==="
  else
    echo ""
    echo "=== [$project_id] Phase 2A: Logged OH Repair + WebVoyager v2 ==="
  fi
  echo "Run dir: $run_dir"
  echo "Starting at: $(date)"

  python3 -u openhands_integration/optimize_batch_results.py \
    --run-dir "$run_dir" \
    --start "$project_id" \
    --end "$project_id" \
    --source-variant "$LOGGED_SOURCE_VARIANT" \
    --branch-name logged \
    --summary-file "$summary_file" \
    --prompt-template "$prompt_template" \
    --timeout 5400 \
    --webvoyager-timeout 1800 \
    --webvoyager-max-iter 10 \
    --repair-rounds 1 \
    "${extra_args[@]}" \
    "${MODEL_ARGS[@]}" \
    2>&1 | tee "$phase2_log"

  assert_phase2_success "$project_id" "$run_dir" "$summary_file" || return 1

  echo "[$project_id] Phase 2A logged complete at: $(date)"
}

run_phase2_no_log_for_project() {
  local project_id="$1"
  local run_dir="$2"
  local summary_file="$run_dir/dynamic_repair_no_log_summary.json"
  local phase2_log="$LOG_DIR/phase2_no_log_${project_id}_${TIMESTAMP}.log"
  local prompt_template="$WORKSPACE/openhands_integration/prompts/no_log_baseline_repair_prompt.txt"

  echo ""
  echo "=== [$project_id] Phase 2B: No-log OH Repair + WebVoyager v2 ==="
  echo "Run dir: $run_dir"
  echo "Starting at: $(date)"

  python3 -u openhands_integration/optimize_batch_results.py \
    --run-dir "$run_dir" \
    --start "$project_id" \
    --end "$project_id" \
    --source-variant clean \
    --branch-name no_log \
    --summary-file "$summary_file" \
    --skip-telemetry-report \
    --skip-llm-brief \
    --prompt-template "$prompt_template" \
    --timeout 5400 \
    --webvoyager-timeout 1800 \
    --webvoyager-max-iter 10 \
    --repair-rounds 1 \
    "${MODEL_ARGS[@]}" \
    2>&1 | tee "$phase2_log"

  assert_phase2_success "$project_id" "$run_dir" "$summary_file" || return 1

  echo "[$project_id] Phase 2B no-log complete at: $(date)"
}

write_baseline_summary_for_project() {
  local project_id="$1"
  local run_dir="$2"
  local out_file="$run_dir/baseline_dual_repair_summary.json"

  python3 - "$run_dir" "$project_id" "$out_file" "$LOGGED_SOURCE_SUFFIX" "$LOGGED_SOURCE_VARIANT" <<'PY'
import json
import pathlib
import sys

run_dir = pathlib.Path(sys.argv[1])
project_id = sys.argv[2]
out_file = pathlib.Path(sys.argv[3])
logged_source_suffix = sys.argv[4]
logged_source_variant = sys.argv[5]

def load_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def first_project(payload):
    projects = payload.get("projects") or []
    return projects[0] if projects else {}

batch = load_json(run_dir / "batch_results.json")
logged_summary = load_json(run_dir / "dynamic_repair_logged_summary.json")
no_log_summary = load_json(run_dir / "dynamic_repair_no_log_summary.json")
logged = first_project(logged_summary)
no_log = first_project(no_log_summary)

gen_dir = run_dir / f"gen_{project_id}"
payload = {
    "project_id": project_id,
    "run_dir": str(run_dir),
    "v1": {
        "clean_source": str(gen_dir / f"project_{project_id}"),
      "logged_source": str(gen_dir / f"project_{project_id}_{logged_source_suffix}"),
      "logged_source_variant": logged_source_variant,
        "webvoyager_results": str(run_dir / "webvoyager_results" / project_id),
        "batch_result": first_project(batch),
    },
    "repairs": {
        "logged": {
            "summary_file": str(run_dir / "dynamic_repair_logged_summary.json"),
            "source_workspace": logged.get("source_workspace"),
            "experiment_workspace": logged.get("experiment_workspace"),
            "phase1_brief": logged.get("phase1_brief"),
            "phase2": logged.get("phase2"),
            "phase3": logged.get("phase3"),
            "quality_gate": logged.get("quality_gate"),
        },
        "no_log": {
            "summary_file": str(run_dir / "dynamic_repair_no_log_summary.json"),
            "source_workspace": no_log.get("source_workspace"),
            "experiment_workspace": no_log.get("experiment_workspace"),
            "phase1": no_log.get("phase1"),
            "phase1_brief": no_log.get("phase1_brief"),
            "phase2": no_log.get("phase2"),
            "phase3": no_log.get("phase3"),
            "quality_gate": no_log.get("quality_gate"),
        },
    },
}
out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(out_file)
PY
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
    --source-variant "$LOGGED_SOURCE_VARIANT" \
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
    --source-variant "$LOGGED_SOURCE_VARIANT" \
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
  HAD_FAILURE=0

  for current_dec in $(seq "$START_DEC" "$END_DEC"); do
    PROJECT_ID="$(printf '%06d' "$current_dec")"

    if [[ "$ONLY_REPAIR_MODE" != "true" ]]; then
      if ! run_phase1_for_project "$PROJECT_ID" "$RUN_DIR" "$TOTAL_PROJECTS"; then
        echo "[$PROJECT_ID] Phase 1 failed; skipping remaining stages for this project and continuing."
        printf '%s\t%s\t%s\n' "$PROJECT_ID" "$RUN_DIR" "phase1_failed" >> "$MANIFEST_PATH"
        HAD_FAILURE=1
        continue
      fi
    else
      echo "[$PROJECT_ID] Only-repair mode: skipping Phase 1"
    fi

    if ! run_phase2_logged_for_project "$PROJECT_ID" "$RUN_DIR"; then
      echo "[$PROJECT_ID] Phase 2A logged failed; skipping remaining stages for this project and continuing."
      printf '%s\t%s\t%s\n' "$PROJECT_ID" "$RUN_DIR" "phase2_logged_failed" >> "$MANIFEST_PATH"
      HAD_FAILURE=1
      continue
    fi

    if [[ "$ONLY_REPAIR_MODE" != "true" ]]; then
      if ! run_phase2_no_log_for_project "$PROJECT_ID" "$RUN_DIR"; then
        echo "[$PROJECT_ID] Phase 2B no-log failed; skipping summary for this project and continuing."
        printf '%s\t%s\t%s\n' "$PROJECT_ID" "$RUN_DIR" "phase2_no_log_failed" >> "$MANIFEST_PATH"
        HAD_FAILURE=1
        continue
      fi
      echo "[$PROJECT_ID] Baseline summary: $(write_baseline_summary_for_project "$PROJECT_ID" "$RUN_DIR")"
    else
      echo "[$PROJECT_ID] Only-repair mode: skipping Phase 2B (no-log) and summary"
    fi
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

FINAL_STATUS=0
if [[ "${HAD_FAILURE:-0}" == "1" ]] || { [[ -n "${MANIFEST_PATH:-}" && -f "$MANIFEST_PATH" ]] && grep -qE $'\tphase(1|2_logged|2_no_log)_failed$' "$MANIFEST_PATH"; }; then
  FINAL_STATUS=1
fi
exit "$FINAL_STATUS"
