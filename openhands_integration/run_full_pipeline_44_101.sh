#!/bin/bash
# Full pipeline for projects 000044-000101
# Phase 1: run_batch.py  → generate + WebVoyager v1
# Phase 2: optimize_batch_results.py → OH repair + WebVoyager v2 + quality gate
#
# Usage:
#   bash openhands_integration/run_full_pipeline_44_101.sh
#   bash openhands_integration/run_full_pipeline_44_101.sh --only-optimize batch_runs/run_YYYYMMDD_XXXXXX
#   bash openhands_integration/run_full_pipeline_44_101.sh --start 000060  # resume from a specific project
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$WORKSPACE/batch_runs/pipeline_logs"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
PIPELINE_LOG="$LOG_DIR/pipeline_44_101_${TIMESTAMP}.log"

# ── Args ────────────────────────────────────────────────────────────────────
START_ID="${START_ID:-000044}"
END_ID="${END_ID:-000101}"
ONLY_OPTIMIZE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --only-optimize)
      ONLY_OPTIMIZE="$2"; shift 2;;
    --start)
      START_ID="$2"; shift 2;;
    --end)
      END_ID="$2"; shift 2;;
    *)
      echo "Unknown arg: $1"; exit 1;;
  esac
done

# ── Logging ─────────────────────────────────────────────────────────────────
exec > >(tee -a "$PIPELINE_LOG") 2>&1
echo "=================================================="
echo "Full Pipeline: $START_ID → $END_ID"
echo "Workspace: $WORKSPACE"
echo "Log: $PIPELINE_LOG"
echo "Started: $(date)"
echo "=================================================="

cd "$WORKSPACE"

# ── Phase 1: Generation + WebVoyager v1 ─────────────────────────────────────
if [[ -n "$ONLY_OPTIMIZE" ]]; then
  RUN_DIR="$ONLY_OPTIMIZE"
  echo "[Phase 1] Skipped — using existing run dir: $RUN_DIR"
else
  echo ""
  echo "=== Phase 1: Generation + WebVoyager v1 (${START_ID} → ${END_ID}) ==="
  echo "Starting at: $(date)"

  # Capture the run dir from the first line of output
  PHASE1_LOG="$LOG_DIR/phase1_${TIMESTAMP}.log"
  python3 -u openhands_integration/run_batch.py \
    --start "$START_ID" \
    --end "$END_ID" \
    2>&1 | tee "$PHASE1_LOG"

  # Extract run dir from log
  RUN_DIR="$(grep -m1 'Batch output:' "$PHASE1_LOG" | sed 's/.*Batch output: //' | tr -d '[:space:]')"

  if [[ -z "$RUN_DIR" ]]; then
    echo "ERROR: Could not extract run dir from Phase 1 output. Check $PHASE1_LOG"
    exit 1
  fi

  echo ""
  echo "Phase 1 complete. Run dir: $RUN_DIR"
  echo "Phase 1 ended at: $(date)"
fi

# ── Phase 2: OH Repair + WebVoyager v2 + Quality Gate ───────────────────────
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
  2>&1 | tee "$LOG_DIR/phase2_${TIMESTAMP}.log"

echo ""
echo "Phase 2 complete at: $(date)"

# ── Phase 3: Analysis Report ─────────────────────────────────────────────────
echo ""
echo "=== Generating Analysis Report ==="
REPORT_PATH="$RUN_DIR/analysis_report.html"

python3 -u openhands_integration/analyze_repair_results.py \
  --run-dir "$RUN_DIR" \
  --output "$REPORT_PATH" \
  2>&1

echo ""
echo "Analysis report: $REPORT_PATH"
echo ""
echo "=================================================="
echo "Pipeline complete at: $(date)"
echo "Run dir:    $RUN_DIR"
echo "Report:     $REPORT_PATH"
echo "Full log:   $PIPELINE_LOG"
echo "=================================================="
