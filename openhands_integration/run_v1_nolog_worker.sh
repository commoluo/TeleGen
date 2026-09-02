#!/usr/bin/env bash
# Docker worker entrypoint: run the no-log v1 WebVoyager evaluation for ONE project.
# Mirrors run_project_worker.sh's env setup but calls run_v1_webvoyager.py instead
# of the full pipeline. Used via launch_multi_docker.py --worker-script.
#
# Env:
#   V1_NOLOG_MODEL      flash | pro  (selects the source manifest; default flash)
#   V1_NOLOG_MANIFEST   override manifest path
#   WEBVOYAGER_NUM_WORKERS, PIPELINE_WEB_STACK_LOCK, TELEGEN_WORKER_HOME  (as original worker)
set -euo pipefail

PROJECT_ID=""
WORKSPACE="${WORKSPACE:-$(pwd)}"
RUN_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --run-dir) RUN_DIR="$2"; shift 2 ;;
    --model) shift 2 ;;                      # accepted from launcher, ignored (unified LLM model not used here)
    --reuse-openhands-workspace) shift ;;    # accepted from launcher, ignored
    -h|--help)
      echo "Usage: $0 --project-id 000022 --workspace <ws> --run-dir <dir> [--model x]"
      exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: --project-id is required" >&2
  exit 2
fi

WORKSPACE="$(cd "$WORKSPACE" && pwd)"
RUN_DIR="${RUN_DIR:-$WORKSPACE/batch_runs/v1_nolog/project_${PROJECT_ID}}"
mkdir -p "$RUN_DIR"

export HOME="${TELEGEN_WORKER_HOME:-/tmp/telegen-home}"
mkdir -p "$HOME"
export WEBVOYAGER_NUM_WORKERS="${WEBVOYAGER_NUM_WORKERS:-2}"
export PIPELINE_WEB_STACK_LOCK="${PIPELINE_WEB_STACK_LOCK:-/tmp/telegen_web_stack_${PROJECT_ID}.lock}"

MODEL="${V1_NOLOG_MODEL:-flash}"
MANIFEST="${V1_NOLOG_MANIFEST:-$WORKSPACE/openhands_integration/v1_source_manifest_${MODEL}.json}"

if [[ ! -f "$MANIFEST" ]]; then
  echo "ERROR: manifest not found: $MANIFEST (V1_NOLOG_MODEL=$MODEL)" >&2
  exit 2
fi

# Resolve the clean v1 source dir for this project from the manifest.
CLEAN_SOURCE="$(python3 - "$MANIFEST" "$PROJECT_ID" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
pid = sys.argv[2]
proj = (manifest.get("projects") or {}).get(pid)
if not proj:
    sys.stderr.write(f"ERROR: {pid} not in manifest {sys.argv[1]}\n"); sys.exit(2)
print(proj["clean_source"])
PY
)"

# Manifest paths are stored relative to the repo root (WORKSPACE);
# keep backward-compat with legacy absolute paths.
if [[ "$CLEAN_SOURCE" != /* ]]; then
  CLEAN_SOURCE="$WORKSPACE/$CLEAN_SOURCE"
fi

if [[ ! -d "$CLEAN_SOURCE" ]]; then
  echo "ERROR: clean source dir does not exist: $CLEAN_SOURCE" >&2
  exit 2
fi

OUTPUT_DIR="$RUN_DIR/webvoyager_results_nolog/$PROJECT_ID"
mkdir -p "$OUTPUT_DIR"

# Resume: skip if this project already has a completed no-log summary.
if [[ "${V1_NOLOG_SKIP_EXISTING:-true}" == "true" ]] && [[ -f "$OUTPUT_DIR/nolog_v1_summary.json" ]]; then
  STATUS="$(python3 - "$OUTPUT_DIR/nolog_v1_summary.json" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("status", ""))
except Exception:
    print("")
PY
)"
  if [[ "$STATUS" == "completed" ]]; then
    echo "[v1-nolog-worker:$PROJECT_ID] SKIP (already completed): $OUTPUT_DIR/nolog_v1_summary.json"
    exit 0
  fi
fi

echo "[v1-nolog-worker:$PROJECT_ID] model=$MODEL manifest=$MANIFEST"
echo "[v1-nolog-worker:$PROJECT_ID] clean_source=$CLEAN_SOURCE"
echo "[v1-nolog-worker:$PROJECT_ID] output_dir=$OUTPUT_DIR"
echo "[v1-nolog-worker:$PROJECT_ID] webvoyager_workers=$WEBVOYAGER_NUM_WORKERS lock=$PIPELINE_WEB_STACK_LOCK"

cd "$WORKSPACE"
exec python3 -u openhands_integration/run_v1_webvoyager.py \
  --source-dir "$CLEAN_SOURCE" \
  --project-id "$PROJECT_ID" \
  --output-dir "$OUTPUT_DIR"
