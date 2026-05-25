#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash openhands_integration/run_project_worker.sh --project-id 000001 [options]

Options:
  --project-id ID       Required project id, e.g. 000001.
  --workspace PATH      Repository path inside the container. Defaults to current directory.
  --run-root PATH       Root directory for all project outputs. Defaults to WORKSPACE/batch_runs/multi_docker_manual.
  --run-dir PATH        Explicit run directory for this project. Overrides --run-root.
  --model MODEL         Unified model passed to the existing full pipeline.
  --reuse-openhands-workspace
                       Keep the existing pipeline's symlink reuse mode. Default copies generated output.
  -h, --help           Show this help.

Environment:
  WEBVOYAGER_NUM_WORKERS       Per-project WebVoyager workers inside the container, default 2.
  PIPELINE_WEB_STACK_LOCK      Lock path inside the container, default /tmp/telegen_web_stack_<project>.lock.
  TELEGEN_WORKER_HOME          HOME used by OpenHands inside this worker, default /tmp/telegen-home.
EOF
}

PROJECT_ID=""
WORKSPACE="${WORKSPACE:-$(pwd)}"
RUN_ROOT=""
RUN_DIR=""
MODEL_NAME="${MODEL_NAME:-}"
REUSE_OPENHANDS_WORKSPACE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    --workspace)
      WORKSPACE="$2"
      shift 2
      ;;
    --run-root)
      RUN_ROOT="$2"
      shift 2
      ;;
    --run-dir)
      RUN_DIR="$2"
      shift 2
      ;;
    --model)
      MODEL_NAME="$2"
      shift 2
      ;;
    --reuse-openhands-workspace)
      REUSE_OPENHANDS_WORKSPACE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: --project-id is required" >&2
  usage >&2
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

PIPELINE_ARGS=(
  openhands_integration/run_full_pipeline_llm_injection.sh
  --start "$PROJECT_ID"
  --end "$PROJECT_ID"
  --run-dir "$RUN_DIR"
)

if [[ -n "$MODEL_NAME" ]]; then
  PIPELINE_ARGS+=(--model "$MODEL_NAME")
fi

if [[ "${RAW_LOGS_MODE:-false}" == "true" ]]; then
  PIPELINE_ARGS+=(--raw-logs)
fi

if [[ "${ONLY_REPAIR_MODE:-false}" == "true" ]]; then
  PIPELINE_ARGS+=(--only-repair)
fi

if [[ "$REUSE_OPENHANDS_WORKSPACE" != "true" ]]; then
  PIPELINE_ARGS+=(--no-reuse-openhands-workspace)
fi

echo "[worker:$PROJECT_ID] workspace=$WORKSPACE"
echo "[worker:$PROJECT_ID] run_dir=$RUN_DIR"
echo "[worker:$PROJECT_ID] home=$HOME"
echo "[worker:$PROJECT_ID] webvoyager_workers=$WEBVOYAGER_NUM_WORKERS"
echo "[worker:$PROJECT_ID] lock=$PIPELINE_WEB_STACK_LOCK"

exec bash "${PIPELINE_ARGS[@]}"