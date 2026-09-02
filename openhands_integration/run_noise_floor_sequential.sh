#!/usr/bin/env bash
# Sequential noise-floor runs: one launcher at a time (avoids container-name
# collisions and resource contention). Each run re-evaluates existing v1 apps
# (no regeneration/instrumentation/repair), 10 workers, alone on the host.
#
# Order: Flash-clean -> Flash-logged -> Pro-clean -> Pro-logged
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$WS"
unset V1_NOLOG_MODEL  # always set V1_NOLOG_MANIFEST explicitly below
LOGS="${LOGS:-$WS/logs}"

run_one () {
  local label="$1" manifest="$2" runroot="$3"
  echo "=============================================================="
  echo "[$(date +%H:%M:%S)] START $label  -> $runroot"
  echo "=============================================================="
  V1_NOLOG_MANIFEST="$manifest" python3 -u openhands_integration/launch_multi_docker.py \
    --container-cli podman --no-mount-docker-sock \
    --worker-script openhands_integration/run_v1_nolog_worker.sh \
    --image localhost/telegen-pipeline:latest \
    --start 000001 --end 000101 --workers 10 \
    --run-root "$runroot" \
    --webvoyager-workers 2 \
    2>&1 | tee "$LOGS/noise_floor_${label}.log"
  echo "[$(date +%H:%M:%S)] DONE  $label (exit ${PIPESTATUS[0]})"
}

run_one "flash_clean"  "$WS/openhands_integration/v1_source_manifest_flash.json"         "batch_runs/official/v1_nolog_flash_rerun2"
run_one "flash_logged" "$WS/openhands_integration/v1_source_manifest_flash_logged.json"  "batch_runs/official/v1_logged_flash_rerun2"
run_one "pro_clean"    "$WS/openhands_integration/v1_source_manifest_pro.json"           "batch_runs/official/v1_nolog_pro_rerun2"
run_one "pro_logged"   "$WS/openhands_integration/v1_source_manifest_pro_logged.json"    "batch_runs/official/v1_logged_pro_rerun2"

echo "=============================================================="
echo "[$(date +%H:%M:%S)] ALL 4 NOISE-FLOOR RUNS COMPLETE"
echo "=============================================================="
