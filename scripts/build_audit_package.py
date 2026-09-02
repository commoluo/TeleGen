#!/usr/bin/env python3
"""Build the TeleGen usability/judgeability audit annotation package.

This adapts the existing human-validation annotation app
(scripts/build_human_validation_package.py) for a 30-case audit where
No-Telemetry Repair = FAIL and TeleGen Repair = SUCCESS. It REUSES the
existing implementation: it imports the existing helpers
(parse_trajectory, safe_symlink, rel_if_possible) and follows the same
static-HTML + per-case-directory + localStorage architecture, the same
page layout, navigation, image modal, and export concept.

The package is written to a SEPARATE directory
(human_validation_telegen/usability_audit/) and uses a SEPARATE
localStorage key + annotation_version so the original 60-case package
and its annotations are left untouched.

Usage:
    python scripts/build_audit_package.py \
        --cases human_validation_telegen/usability_audit/usability_audit_cases.json \
        --output human_validation_telegen/usability_audit \
        --workspace .

    # 2-mock-case smoke/test build:
    python scripts/build_audit_package.py \
        --cases human_validation_telegen/usability_audit/example_cases.json \
        --output /tmp/audit_example --workspace . --force
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse the existing implementation's helpers (do not duplicate them).
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
import build_human_validation_package as bhp  # noqa: E402

ANNOTATION_VERSION = "telegen-usability-audit-v1"
LOCALSTORAGE_KEY = "telegen_usability_audit_progress"

# ── Export schema (every saved / exported record) ───────────────────
EXPORT_FIELDS = [
    "sample_id", "project_id", "task_id",
    "functional_postconditions",
    "no_telemetry_functional_status", "telegen_functional_status",
    "genuine_functional_change",
    "judgeability_improvement", "judgeability_types", "judgeability_other",
    "shortcut_or_exploitation", "shortcut_indicators", "shortcut_other",
    "counterfactual_status", "counterfactual_notes",
    "primary_classification", "confidence",
    "evidence", "visual_confirmation_notes", "needs_further_review",
    "annotator_id", "annotation_timestamp", "annotation_version",
]

JUDGEABILITY_TYPES = [
    "Control or action became easier to discover",
    "Button or control received clearer text",
    "Semantic label or aria-label was added",
    "Required panel or section became directly accessible",
    "Number of interaction steps was reduced",
    "Navigation became easier",
    "Completion state became easier to observe",
    "Success or error feedback became clearer",
    "Relevant content became visible by default",
    "Layout or interaction flow became easier to understand",
    "Other",
]
SHORTCUT_INDICATORS = [
    "Task-specific value was hard-coded",
    "Expected result was used as the default state",
    "Success message appeared without a genuine state update",
    "Required validation or workflow step was bypassed",
    "Only displayed text changed",
    "Behavior appears limited to the exact benchmark input",
    "Target page or state was opened automatically",
    "Underlying data was not updated",
    "Other",
]
CLASSIFICATIONS = [
    "Genuine Functional Repair",
    "Judgeability/Usability Improvement Only",
    "Mixed Functional and Judgeability Repair",
    "Evaluator Exploitation or Task-Specific Shortcut",
    "Uncertain",
]


# ── Evidence collection ─────────────────────────────────────────────

def _read_eval(eval_path: str) -> Dict[str, str]:
    if eval_path and os.path.exists(eval_path):
        try:
            d = json.loads(Path(eval_path).read_text(encoding="utf-8"))
            return {
                "verdict": d.get("status", ""),
                "answer": d.get("answer", ""),
                "evaluator_response": d.get("evaluator_response", ""),
            }
        except Exception:
            pass
    return {"verdict": "", "answer": "", "evaluator_response": ""}


def _list_screenshots(task_dir: str) -> List[str]:
    if not task_dir or not os.path.isdir(task_dir):
        return []
    return sorted(
        f for f in os.listdir(task_dir)
        if f.startswith("screenshot") and f.endswith(".png")
    )


def _trajectory_html(traj_path: str) -> str:
    steps = bhp.parse_trajectory(traj_path)
    if not steps:
        return "<p>Not available in stored experiment artifacts.</p>"
    parts = []
    for s in steps:
        ss = (
            f' <em style="color:#888;">[{html.escape(s["screenshot"])}]</em>'
            if s.get("screenshot") else ""
        )
        parts.append(
            f'<div class="trajectory-step">'
            f'<span class="step-num">Step {s["step"]}</span>{ss}'
            f'<div class="thought">{html.escape(s["thought"])}</div>'
            f'<div class="action">{html.escape(s["action"])}</div>'
            f'</div>'
        )
    return "\n".join(parts)


def _gallery_html(task_dir: str, prefix: str) -> str:
    shots = _list_screenshots(task_dir)
    if not shots:
        return "<p>Not available in stored experiment artifacts.</p>"
    parts = []
    for i, name in enumerate(shots):
        rel = f"screenshots/{prefix}_{i+1:03d}.png"
        parts.append(
            f'<img src="{rel}" alt="{prefix} step {i+1}" '
            f'title="{prefix} step {i+1}" onclick="showImg(this.src)">'
        )
    return "\n".join(parts)


def _final_html(task_dir: str, prefix: str) -> str:
    shots = _list_screenshots(task_dir)
    if not shots:
        return "<p>Not available in stored experiment artifacts.</p>"
    rel = f"screenshots/{prefix}_final.png"
    return f'<img src="{rel}" alt="{prefix} final screenshot" onclick="showImg(this.src)">'


def _symlink_screenshots(task_dir: str, ss_dir: Path, prefix: str) -> None:
    shots = _list_screenshots(task_dir)
    for i, name in enumerate(shots):
        src = Path(task_dir) / name
        if i == len(shots) - 1:
            dst = ss_dir / f"{prefix}_final.png"
        else:
            dst = ss_dir / f"{prefix}_{i+1:03d}.png"
        bhp.safe_symlink(src, dst, copy=False)


# ── HTML templates ──────────────────────────────────────────────────

REVIEW_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audit {{CASE_ID}}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 0; background: #f5f5f5; color: #333; }
  .container { max-width: 1100px; margin: 0 auto; padding: 1.5rem; }
  .nav { display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 1.5rem; background: #fff; border-radius: 8px;
          padding: .75rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .nav a { text-decoration: none; color: #1976d2; font-weight: 500; }
  .nav .case-id { font-weight: 700; font-size: 1.2rem; }
  section { background: #fff; border-radius: 8px; padding: 1.5rem; margin-bottom: 1rem;
             box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  h2 { margin-top: 0; font-size: 1.25rem; color: #222; }
  h3 { margin: 0 0 .5rem; font-size: 1.05rem; color: #1976d2; }
  .meta { display: grid; grid-template-columns: 160px 1fr; gap: .25rem 1rem; font-size: .95rem; }
  .meta .k { font-weight: 600; color: #555; }
  .badge { display: inline-block; padding: .1rem .5rem; border-radius: 4px; font-size: .85rem; font-weight: 600; }
  .badge.fail { background: #fdecea; color: #c62828; }
  .badge.pass { background: #e8f5e9; color: #2e7d32; }
  .versions { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  .version { background: #fafafa; border-radius: 6px; padding: 1rem; border-top: 3px solid #1976d2; }
  .version.nt { border-top-color: #c62828; }
  .version.tg { border-top-color: #2e7d32; }
  .trajectory-step { border-left: 3px solid #e0e0e0; padding-left: 1rem; margin-bottom: 1rem; }
  .trajectory-step .step-num { font-weight: 700; color: #1976d2; }
  .trajectory-step .thought { color: #555; margin: .25rem 0; font-size: .9rem; }
  .trajectory-step .action { color: #333; font-weight: 500; font-size: .9rem; }
  .screenshots { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .5rem; }
  .screenshots img { width: 160px; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; }
  .final-screenshot img { width: 100%; max-width: 480px; border: 1px solid #ddd; border-radius: 6px; }
  .annotate { background: #fffde7; border-radius: 8px; padding: 1.5rem;
               box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .annotate .field { margin-bottom: 1rem; }
  .annotate label { font-weight: 600; display: block; margin-bottom: .25rem; }
  .annotate .help { font-size: .85rem; color: #777; font-weight: normal; margin: .15rem 0 .4rem; }
  .annotate input[type=text], .annotate textarea { width: 100%; padding: .4rem;
       border: 1px solid #ccc; border-radius: 4px; font-size: .95rem; box-sizing: border-box; }
  .annotate textarea { min-height: 60px; }
  .annotate .radio-row, .annotate .checks { display: flex; flex-wrap: wrap; gap: .6rem 1.2rem; }
  .annotate .checks label { font-weight: normal; }
  .req { color: #c62828; }
  .conditional { display: none; padding-left: 1rem; border-left: 2px solid #ffe082; margin: .4rem 0; }
  .warning { background: #fff3cd; border: 1px solid #ffe082; border-radius: 4px;
             padding: .5rem .75rem; margin: .4rem 0; font-size: .9rem; color: #8a6d3b; }
  .actions { margin-top: 1rem; display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
  button { padding: .4rem 1rem; cursor: pointer; border: 1px solid #1976d2; background: #1976d2;
           color: #fff; border-radius: 4px; font-size: .95rem; }
  button.secondary { background: #fff; color: #1976d2; }
  #saved-msg { color: green; font-size: .9rem; display: none; }
  .reveal summary { cursor: pointer; font-weight: 600; color: #d32f2f; padding: .5rem; }
  .reveal-content { padding: 1rem; background: #fff3e0; border-radius: 6px; margin-top: .5rem; }
  .reveal-content pre { white-space: pre-wrap; font-size: .85rem; }
  .source-link { margin-top: .5rem; font-size: .9rem; }
  .source-link a { color: #666; text-decoration: none; }
  .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0;
           width: 100%; height: 100%; background: rgba(0,0,0,.8); }
  .modal img { max-width: 95%; max-height: 95%; margin: auto; display: block; padding-top: 2rem; }
</style>
</head>
<body>
<div class="container">
  <div class="nav">
    <a href="{{PREV_HREF}}" {{PREV_DISABLED}}>&larr; Previous</a>
    <span class="case-id">{{CASE_ID}} ({{SAMPLE_NO}}/{{TOTAL_CASES}})</span>
    <a href="{{NEXT_HREF}}" {{NEXT_DISABLED}}>Next &rarr;</a>
  </div>
  <div style="text-align:center;margin-bottom:1rem;"><a href="../index.html">&larr; Back to all cases</a></div>

  <section>
    <h2>Case Information</h2>
    <div class="meta">
      <div class="k">Sample No.</div><div>{{SAMPLE_NO}}</div>
      <div class="k">Project ID</div><div>{{PROJECT_ID}}</div>
      <div class="k">Task ID</div><div>{{TASK_ID}}</div>
      <div class="k">Task description</div><div>{{TASK_DESC}}</div>
      <div class="k">Expected result</div><div>{{EXPECTED}}</div>
      <div class="k">Category</div><div>{{CATEGORY}}{{SUBCAT}}</div>
      <div class="k">No-Telemetry result</div><div><span class="badge fail">FAIL</span> (verdict: {{NT_VERDICT}})</div>
      <div class="k">TeleGen result</div><div><span class="badge pass">SUCCESS</span> (verdict: {{TG_VERDICT}})</div>
    </div>
  </section>

  <section>
    <h2>Execution Evidence — both versions</h2>
    <p class="help" style="margin-top:0">Compare the No-Telemetry Repair (FAIL) and TeleGen Repair (SUCCESS) side by side. Each panel shows the WebVoyager agent's trajectory, screenshots, and the evaluator's verdict.</p>
    <div class="versions">
      <div class="version nt">
        <h3>No-Telemetry Repair <span class="badge fail">FAIL</span></h3>
        <details class="reveal"><summary>Trajectory ({{NT_STEP_COUNT}} steps)</summary><div class="reveal-content">{{NT_TRAJECTORY}}</div></details>
        <h3 style="margin-top:1rem">Screenshots</h3>
        <div class="screenshots">{{NT_GALLERY}}</div>
        <h3 style="margin-top:1rem">Final screenshot</h3>
        <div class="final-screenshot">{{NT_FINAL}}</div>
        <details class="reveal" style="margin-top:1rem"><summary>Reveal evaluator judgment</summary>
          <div class="reveal-content">
            <p><strong>Verdict:</strong> {{NT_VERDICT}} &nbsp; <strong>Answer:</strong> {{NT_ANSWER}}</p>
            <pre>{{NT_EVAL}}</pre>
          </div>
        </details>
      </div>
      <div class="version tg">
        <h3>TeleGen Repair <span class="badge pass">SUCCESS</span></h3>
        <details class="reveal"><summary>Trajectory ({{TG_STEP_COUNT}} steps)</summary><div class="reveal-content">{{TG_TRAJECTORY}}</div></details>
        <h3 style="margin-top:1rem">Screenshots</h3>
        <div class="screenshots">{{TG_GALLERY}}</div>
        <h3 style="margin-top:1rem">Final screenshot</h3>
        <div class="final-screenshot">{{TG_FINAL}}</div>
        <details class="reveal" style="margin-top:1rem"><summary>Reveal evaluator judgment</summary>
          <div class="reveal-content">
            <p><strong>Verdict:</strong> {{TG_VERDICT}} &nbsp; <strong>Answer:</strong> {{TG_ANSWER}}</p>
            <pre>{{TG_EVAL}}</pre>
          </div>
        </details>
      </div>
    </div>
  </section>

  <section class="annotate">
    <h2>Annotation</h2>
    <div id="warnings"></div>

    <div class="field">
      <label>1. Functional postconditions required by the task</label>
      <div class="help">Describe the actual state or behavior that must be achieved for the task to be functionally correct. Do not treat a success message or visible target text alone as proof of correctness.</div>
      <textarea id="functional_postconditions" placeholder="e.g. The submitted item is persisted to the store and appears in the list on reload."></textarea>
    </div>

    <div class="field">
      <label>2. Does the No-Telemetry version satisfy the functional postconditions?</label>
      <div class="radio-row" data-radio="no_telemetry_functional_status">
        <label><input type="radio" name="no_telemetry_functional_status" value="Functionally correct"> Functionally correct</label>
        <label><input type="radio" name="no_telemetry_functional_status" value="Partially correct"> Partially correct</label>
        <label><input type="radio" name="no_telemetry_functional_status" value="Functionally incorrect"> Functionally incorrect</label>
        <label><input type="radio" name="no_telemetry_functional_status" value="Unable to determine"> Unable to determine</label>
      </div>
    </div>

    <div class="field">
      <label>3. Does the TeleGen version satisfy the functional postconditions?</label>
      <div class="radio-row">
        <label><input type="radio" name="telegen_functional_status" value="Functionally correct"> Functionally correct</label>
        <label><input type="radio" name="telegen_functional_status" value="Partially correct"> Partially correct</label>
        <label><input type="radio" name="telegen_functional_status" value="Functionally incorrect"> Functionally incorrect</label>
        <label><input type="radio" name="telegen_functional_status" value="Unable to determine"> Unable to determine</label>
      </div>
    </div>

    <div class="field">
      <label>4. Did TeleGen fix at least one functional postcondition that was not satisfied by the No-Telemetry version?</label>
      <div class="help">Select "Yes" only when there is evidence of a real change in application behavior, state, event handling, data flow, navigation, validation, or persistence.</div>
      <div class="radio-row">
        <label><input type="radio" name="genuine_functional_change" value="Yes"> Yes</label>
        <label><input type="radio" name="genuine_functional_change" value="No"> No</label>
        <label><input type="radio" name="genuine_functional_change" value="Unclear"> Unclear</label>
      </div>
    </div>

    <div class="field">
      <label>5. Did TeleGen make the task easier to discover, perform, or verify?</label>
      <div class="help">Examples: clearer labels, more explicit controls, visible confirmation, reduced interaction steps, default expansion, improved navigation, more observable result.</div>
      <div class="radio-row">
        <label><input type="radio" name="judgeability_improvement" value="Yes"> Yes</label>
        <label><input type="radio" name="judgeability_improvement" value="No"> No</label>
        <label><input type="radio" name="judgeability_improvement" value="Possible but unclear"> Possible but unclear</label>
      </div>
    </div>

    <div class="field conditional" id="judgeability_types_block">
      <label>6. Judgeability improvement types (select all that apply)</label>
      <div class="checks">
        {{JUDGEABILITY_TYPES_HTML}}
      </div>
      <div id="judgeability_other_row" style="display:none;margin-top:.5rem">
        <label style="font-weight:normal">Other (describe):</label>
        <input type="text" id="judgeability_other" placeholder="describe the other improvement">
      </div>
    </div>

    <div class="field">
      <label>7. Is there evidence that the task passed without genuinely implementing the required behavior?</label>
      <div class="help">Evidence: hard-coded task values, directly initialized target states, success messages without state changes, skipped required steps, behavior that only works for the exact benchmark input, superficial text changes that satisfy the judge.</div>
      <div class="radio-row">
        <label><input type="radio" name="shortcut_or_exploitation" value="Yes"> Yes</label>
        <label><input type="radio" name="shortcut_or_exploitation" value="No"> No</label>
        <label><input type="radio" name="shortcut_or_exploitation" value="Possible but unclear"> Possible but unclear</label>
      </div>
    </div>

    <div class="field conditional" id="shortcut_indicators_block">
      <label>8. Shortcut indicators (select all that apply)</label>
      <div class="checks">
        {{SHORTCUT_INDICATORS_HTML}}
      </div>
      <div id="shortcut_other_row" style="display:none;margin-top:.5rem">
        <label style="font-weight:normal">Other (describe):</label>
        <input type="text" id="shortcut_other" placeholder="describe the other shortcut">
      </div>
    </div>

    <div class="field">
      <label>9. Did the repair work under an alternative input or equivalent interaction path?</label>
      <div class="radio-row">
        <label><input type="radio" name="counterfactual_status" value="Passed"> Passed</label>
        <label><input type="radio" name="counterfactual_status" value="Failed"> Failed</label>
        <label><input type="radio" name="counterfactual_status" value="Not applicable"> Not applicable</label>
        <label><input type="radio" name="counterfactual_status" value="Not tested"> Not tested</label>
      </div>
      <label style="font-weight:normal;margin-top:.5rem">Counterfactual test performed and result (optional):</label>
      <textarea id="counterfactual_notes" placeholder="e.g. Tried a different ingredient name; analysis still resolved it."></textarea>
    </div>

    <div class="field">
      <label>10. Final classification <span class="req">*</span></label>
      <details><summary>Show category definitions</summary>
        <div class="help" style="background:#f5f5f5;padding:.75rem;border-radius:4px">
          <p><strong>Genuine Functional Repair:</strong> TeleGen repairs at least one previously violated functional postcondition, without the main gain being attributable to judgeability changes.</p>
          <p><strong>Judgeability/Usability Improvement Only:</strong> The underlying functionality was already correct or was not materially repaired; the main change makes the task easier for the evaluator to find, execute, or verify.</p>
          <p><strong>Mixed Functional and Judgeability Repair:</strong> TeleGen both repairs genuine functionality and improves discoverability, usability, or result observability.</p>
          <p><strong>Evaluator Exploitation or Task-Specific Shortcut:</strong> The evaluator reports success, but the required functional postconditions remain unsatisfied or the implementation relies on a task-specific shortcut.</p>
          <p><strong>Uncertain:</strong> The available evidence is insufficient for a reliable classification.</p>
        </div>
      </details>
      <div class="radio-row" style="flex-direction:column;gap:.3rem">
        {{CLASSIFICATIONS_HTML}}
      </div>
    </div>

    <div class="field">
      <label>11. Classification confidence</label>
      <div class="radio-row">
        <label><input type="radio" name="confidence" value="High"> High</label>
        <label><input type="radio" name="confidence" value="Medium"> Medium</label>
        <label><input type="radio" name="confidence" value="Low"> Low</label>
      </div>
    </div>

    <div class="field">
      <label>12. Evidence supporting the classification</label>
      <div class="help">Record concrete runtime behavior, state changes, code differences, navigation behavior, logs, or visible evidence. Avoid conclusions based only on the evaluator's PASS/FAIL result.</div>
      <textarea id="evidence" placeholder="Concrete evidence..."></textarea>
    </div>

    <div class="field">
      <label>13. Manual visual confirmation notes</label>
      <div class="help">Record observations from screenshots or rendered applications (controls easier to locate, completion state more visible, etc.). Must be completed manually by the human annotator.</div>
      <textarea id="visual_confirmation_notes" placeholder="Visual observations..."></textarea>
    </div>

    <div class="field">
      <label><input type="checkbox" id="needs_further_review" value="Yes"> 14. This case requires additional execution, code inspection, or discussion</label>
    </div>

    <div class="field">
      <label>Annotator ID</label>
      <input type="text" id="annotator_id" placeholder="your ID">
    </div>

    <div class="actions">
      <button onclick="saveProgress()">Save annotation</button>
      <button class="secondary" onclick="exportAll()">Export all annotations (CSV+JSON)</button>
      <span id="saved-msg">Saved!</span>
    </div>
  </section>

  <div class="source-link">
    <details><summary>Application source directories (only if needed)</summary>
      <p><strong>No-Telemetry:</strong> <a href="source_paths.md">{{NT_SOURCE}}</a></p>
      <p><strong>TeleGen:</strong> <a href="source_paths.md">{{TG_SOURCE}}</a></p>
      <p><strong>v1 (original):</strong> {{V1_SOURCE}}</p>
    </details>
  </div>
</div>

<div class="modal" id="img-modal" onclick="this.style.display='none'">
  <img id="modal-img" src="">
</div>

<script>
const CASE_ID = "{{CASE_ID}}";
const ANNOTATION_VERSION = "{{ANNOTATION_VERSION}}";
const LS_KEY = "{{LS_KEY}}";
const EXPORT_FIELDS = {{EXPORT_FIELDS_JSON}};

function showImg(src) {
  document.getElementById('modal-img').src = src;
  document.getElementById('img-modal').style.display = 'block';
}
function getStore() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); }
  catch(e) { return {}; }
}
function setStore(s) { localStorage.setItem(LS_KEY, JSON.stringify(s)); }

function collectForm() {
  const getRadio = (name) => {
    const el = document.querySelector('input[name="' + name + '"]:checked');
    return el ? el.value : '';
  };
  const getChecks = (name) => {
    return Array.from(document.querySelectorAll('input[name="' + name + '"]:checked')).map(e => e.value);
  };
  const rec = {
    sample_id: {{SAMPLE_NO}},
    project_id: "{{PROJECT_ID}}",
    task_id: "{{TASK_ID}}",
    functional_postconditions: document.getElementById('functional_postconditions').value,
    no_telemetry_functional_status: getRadio('no_telemetry_functional_status'),
    telegen_functional_status: getRadio('telegen_functional_status'),
    genuine_functional_change: getRadio('genuine_functional_change'),
    judgeability_improvement: getRadio('judgeability_improvement'),
    judgeability_types: getChecks('judgeability_types').join('|'),
    judgeability_other: document.getElementById('judgeability_other').value,
    shortcut_or_exploitation: getRadio('shortcut_or_exploitation'),
    shortcut_indicators: getChecks('shortcut_indicators').join('|'),
    shortcut_other: document.getElementById('shortcut_other').value,
    counterfactual_status: getRadio('counterfactual_status'),
    counterfactual_notes: document.getElementById('counterfactual_notes').value,
    primary_classification: getRadio('primary_classification'),
    confidence: getRadio('confidence'),
    evidence: document.getElementById('evidence').value,
    visual_confirmation_notes: document.getElementById('visual_confirmation_notes').value,
    needs_further_review: document.getElementById('needs_further_review').checked ? 'Yes' : 'No',
    annotator_id: document.getElementById('annotator_id').value,
    annotation_timestamp: new Date().toISOString(),
    annotation_version: ANNOTATION_VERSION
  };
  return rec;
}

function setRadio(name, val) {
  if (!val) return;
  const el = document.querySelector('input[name="' + name + '"][value="' + val.replace(/"/g,'\\\\"') + '"]');
  if (el) el.checked = true;
}
function setChecks(name, val) {
  if (!val) return;
  String(val).split('|').forEach(v => {
    const el = document.querySelector('input[name="' + name + '"][value="' + v.replace(/"/g,'\\\\"') + '"]');
    if (el) el.checked = true;
  });
}
function restoreForm(rec) {
  if (!rec) return;
  document.getElementById('functional_postconditions').value = rec.functional_postconditions || '';
  setRadio('no_telemetry_functional_status', rec.no_telemetry_functional_status);
  setRadio('telegen_functional_status', rec.telegen_functional_status);
  setRadio('genuine_functional_change', rec.genuine_functional_change);
  setRadio('judgeability_improvement', rec.judgeability_improvement);
  setChecks('judgeability_types', rec.judgeability_types);
  document.getElementById('judgeability_other').value = rec.judgeability_other || '';
  setRadio('shortcut_or_exploitation', rec.shortcut_or_exploitation);
  setChecks('shortcut_indicators', rec.shortcut_indicators);
  document.getElementById('shortcut_other').value = rec.shortcut_other || '';
  setRadio('counterfactual_status', rec.counterfactual_status);
  document.getElementById('counterfactual_notes').value = rec.counterfactual_notes || '';
  setRadio('primary_classification', rec.primary_classification);
  setRadio('confidence', rec.confidence);
  document.getElementById('evidence').value = rec.evidence || '';
  document.getElementById('visual_confirmation_notes').value = rec.visual_confirmation_notes || '';
  document.getElementById('needs_further_review').checked = rec.needs_further_review === 'Yes';
  document.getElementById('annotator_id').value = rec.annotator_id || '';
}

function updateConditional() {
  const ji = document.querySelector('input[name="judgeability_improvement"]:checked');
  const showJ = ji && (ji.value === 'Yes' || ji.value === 'Possible but unclear');
  document.getElementById('judgeability_types_block').style.display = showJ ? 'block' : 'none';
  const jiOther = document.querySelector('input[name="judgeability_types"][value="Other"]');
  document.getElementById('judgeability_other_row').style.display = (jiOther && jiOther.checked) ? 'block' : 'none';
  const sc = document.querySelector('input[name="shortcut_or_exploitation"]:checked');
  const showS = sc && (sc.value === 'Yes' || sc.value === 'Possible but unclear');
  document.getElementById('shortcut_indicators_block').style.display = showS ? 'block' : 'none';
  const scOther = document.querySelector('input[name="shortcut_indicators"][value="Other"]');
  document.getElementById('shortcut_other_row').style.display = (scOther && scOther.checked) ? 'block' : 'none';
  updateWarnings();
}

function warn(msg) {
  const d = document.createElement('div');
  d.className = 'warning';
  d.textContent = msg;
  document.getElementById('warnings').appendChild(d);
}
function updateWarnings() {
  const box = document.getElementById('warnings');
  box.innerHTML = '';
  const rec = collectForm();
  // 1. genuine_functional_change No but classification Genuine
  if (rec.genuine_functional_change === 'No' && rec.primary_classification === 'Genuine Functional Repair')
    warn('Warning: "Genuine functional change" is "No" but classification is "Genuine Functional Repair".');
  // 2. TeleGen Functionally incorrect but classification Genuine
  if (rec.telegen_functional_status === 'Functionally incorrect' && rec.primary_classification === 'Genuine Functional Repair')
    warn('Warning: TeleGen marked "Functionally incorrect" but classification is "Genuine Functional Repair".');
  // 3. shortcut Yes but classification not Exploitation
  if (rec.shortcut_or_exploitation === 'Yes' && rec.primary_classification !== 'Evaluator Exploitation or Task-Specific Shortcut')
    warn('Warning: "Task-specific shortcut" is "Yes" but classification is not "Evaluator Exploitation or Task-Specific Shortcut".');
  // 4. both genuine and judgeability Yes but classification not Mixed
  if (rec.genuine_functional_change === 'Yes' && rec.judgeability_improvement === 'Yes' && rec.primary_classification !== 'Mixed Functional and Judgeability Repair')
    warn('Warning: Both genuine functional change and judgeability improvement are "Yes" but classification is not "Mixed Functional and Judgeability Repair".');
  // 5. either functional status Unable to determine and confidence High
  if ((rec.no_telemetry_functional_status === 'Unable to determine' || rec.telegen_functional_status === 'Unable to determine') && rec.confidence === 'High')
    warn('Warning: A functional status is "Unable to determine" but confidence is "High".');
}

function saveProgress() {
  const rec = collectForm();
  if (!rec.primary_classification) { alert('Please select a Final classification (field 10) before saving.'); return; }
  const store = getStore();
  // version-gated: do not overwrite records from a different annotation version
  const existing = store[CASE_ID];
  if (existing && existing.annotation_version && existing.annotation_version !== ANNOTATION_VERSION) {
    if (!confirm('A record from a different annotation version (' + existing.annotation_version + ') exists for this case. Overwrite it?')) return;
  }
  store[CASE_ID] = rec;
  setStore(store);
  const msg = document.getElementById('saved-msg');
  msg.style.display = 'inline';
  setTimeout(() => msg.style.display = 'none', 2000);
  updateWarnings();
}

function exportAll() {
  const store = getStore();
  const rows = [];
  for (const k in store) {
    const r = store[k];
    if (r && r.annotation_version === ANNOTATION_VERSION) {
      const row = {};
      EXPORT_FIELDS.forEach(f => { row[f] = r[f] !== undefined ? r[f] : ''; });
      rows.push(row);
    }
  }
  // CSV
  const csv = [EXPORT_FIELDS.join(',')].concat(
    rows.map(r => EXPORT_FIELDS.map(f => {
      const v = String(r[f] == null ? '' : r[f]).replace(/"/g, '""');
      return /[",\\n]/.test(v) ? '"' + v + '"' : v;
    }).join(','))
  ).join('\\n');
  const csvBlob = new Blob([csv], {type: 'text/csv'});
  const csvUrl = URL.createObjectURL(csvBlob);
  const a1 = document.createElement('a'); a1.href = csvUrl; a1.download = 'usability_audit_annotations.csv'; a1.click();
  // JSON
  const jsonBlob = new Blob([JSON.stringify(rows, null, 2)], {type: 'application/json'});
  const jsonUrl = URL.createObjectURL(jsonBlob);
  const a2 = document.createElement('a'); a2.href = jsonUrl; a2.download = 'usability_audit_annotations.json'; a2.click();
}

// wire up
document.querySelectorAll('input[type=radio], input[type=checkbox]').forEach(el => {
  el.addEventListener('change', updateConditional);
});
// restore (version-gated)
(function() {
  const store = getStore();
  const rec = store[CASE_ID];
  if (rec && rec.annotation_version === ANNOTATION_VERSION) restoreForm(rec);
  updateConditional();
})();
</script>
</body>
</html>
"""


INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TeleGen Usability Audit</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 2rem; background: #f5f5f5; color: #333; }
  h1 { color: #222; }
  .summary { background: #fff; border-radius: 8px; padding: 1rem 1.5rem; margin-bottom: 1.5rem;
              box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: .75rem; }
  .card { background: #fff; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,.1);
           text-decoration: none; color: #333; transition: transform .1s; }
  .card:hover { transform: translateY(-2px); box-shadow: 0 3px 6px rgba(0,0,0,.15); }
  .card .id { font-weight: 600; font-size: 1.1rem; }
  .card .status { font-size: .8rem; color: #888; margin-top: .3rem; }
  .done { border-left: 4px solid #4caf50; }
  .pending { border-left: 4px solid #e0e0e0; }
  .stats { display: flex; gap: 2rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .stat { text-align: center; }
  .stat .num { font-size: 1.8rem; font-weight: 700; color: #1976d2; }
  .stat .lbl { font-size: .8rem; color: #888; }
  table { border-collapse: collapse; margin-top: .5rem; }
  td, th { padding: .2rem .6rem; border-bottom: 1px solid #eee; font-size: .9rem; }
  .actions { margin: 1rem 0; }
  button { padding: .4rem 1rem; cursor: pointer; border: 1px solid #1976d2; background: #1976d2;
           color: #fff; border-radius: 4px; }
</style>
</head>
<body>
<h1>TeleGen Usability / Judgeability Audit</h1>
<div class="summary">
  <p><strong>Subset:</strong> No-Telemetry Repair = FAIL, TeleGen Repair = SUCCESS</p>
  <p><strong>Cases:</strong> {{TOTAL_CASES}} &nbsp; <strong>Seed:</strong> {{SEED}} &nbsp; <strong>Annotation version:</strong> {{ANNOTATION_VERSION}}</p>
  <div class="stats">
    <div class="stat"><div class="num" id="done-count">0</div><div class="lbl">Completed</div></div>
    <div class="stat"><div class="num">{{TOTAL_CASES}}</div><div class="lbl">Total</div></div>
    <div class="stat"><div class="num" id="remaining">0</div><div class="lbl">Remaining</div></div>
    <div class="stat"><div class="num" id="further">0</div><div class="lbl">Needs further review</div></div>
  </div>
  <div class="actions">
    <button onclick="exportAllIndex()">Export all annotations (CSV+JSON)</button>
  </div>
  <h3>Primary classification distribution</h3>
  <table id="class-table">
    <tr><th>Classification</th><th>Count</th><th>%</th></tr>
  </table>
  <h3>Summary groups</h3>
  <table id="group-table">
    <tr><th>Group</th><th>Count</th><th>%</th></tr>
  </table>
</div>
<div class="grid" id="case-grid">
{{CARDS}}
</div>
<script>
const LS_KEY = "{{LS_KEY}}";
const ANNOTATION_VERSION = "{{ANNOTATION_VERSION}}";
const TOTAL = {{TOTAL_CASES}};
const CASE_IDS = {{CASE_IDS_JSON}};
const CLASSIFICATIONS = {{CLASSIFICATIONS_JSON}};
function getStore() { try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch(e) { return {}; } }
function refresh() {
  const p = getStore(); let done = 0, further = 0;
  const classCounts = {}; CLASSIFICATIONS.forEach(c => classCounts[c] = 0);
  CASE_IDS.forEach(id => {
    const card = document.querySelector('.card[data-case-id="' + id + '"]');
    const rec = p[id];
    if (rec && rec.annotation_version === ANNOTATION_VERSION && rec.primary_classification) {
      done++;
      if (rec.needs_further_review === 'Yes') further++;
      if (classCounts[rec.primary_classification] !== undefined) classCounts[rec.primary_classification]++;
      if (card) { card.classList.add('done'); card.classList.remove('pending');
        card.querySelector('.status').textContent = rec.primary_classification + ' (' + (rec.confidence||'') + ')'; }
    } else if (card) {
      card.classList.add('pending'); card.classList.remove('done');
      card.querySelector('.status').textContent = 'Not yet reviewed';
    }
  });
  document.getElementById('done-count').textContent = done;
  document.getElementById('remaining').textContent = TOTAL - done;
  document.getElementById('further').textContent = further;
  const ct = document.getElementById('class-table');
  CLASSIFICATIONS.forEach(c => {
    const n = classCounts[c]; const pct = TOTAL ? (100*n/TOTAL).toFixed(1) : '0.0';
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + c + '</td><td>' + n + '</td><td>' + pct + '%</td>';
    ct.appendChild(tr);
  });
  const genuine = (classCounts['Genuine Functional Repair']||0) + (classCounts['Mixed Functional and Judgeability Repair']||0);
  const judgeOnly = classCounts['Judgeability/Usability Improvement Only']||0;
  const exploit = classCounts['Evaluator Exploitation or Task-Specific Shortcut']||0;
  const uncertain = classCounts['Uncertain']||0;
  const gt = document.getElementById('group-table');
  const rows = [
    ['Contains a genuine functional repair (Genuine + Mixed)', genuine],
    ['Judgeability-only', judgeOnly],
    ['Evaluator exploitation / shortcut', exploit],
    ['Uncertain', uncertain],
    ['Needs further review', further],
  ];
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + r[0] + '</td><td>' + r[1] + '</td><td>' + (TOTAL?(100*r[1]/TOTAL).toFixed(1):'0.0') + '%</td>';
    gt.appendChild(tr);
  });
}
function exportAllIndex() {
  const store = getStore();
  const fields = {{EXPORT_FIELDS_JSON}};
  const rows = [];
  for (const k in store) {
    const r = store[k];
    if (r && r.annotation_version === ANNOTATION_VERSION) {
      const row = {}; fields.forEach(f => row[f] = r[f] !== undefined ? r[f] : '');
      rows.push(row);
    }
  }
  const csv = [fields.join(',')].concat(rows.map(r => fields.map(f => {
    const v = String(r[f]==null?'':r[f]).replace(/"/g,'""');
    return /[",\\n]/.test(v)?'"'+v+'"':v;
  }).join(','))).join('\\n');
  const a1 = document.createElement('a'); a1.href = URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a1.download = 'usability_audit_annotations.csv'; a1.click();
  const a2 = document.createElement('a'); a2.href = URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));
  a2.download = 'usability_audit_annotations.json'; a2.click();
}
window.addEventListener('focus', refresh);
window.addEventListener('storage', refresh);
refresh();
</script>
</body>
</html>
"""


# ── Generation ──────────────────────────────────────────────────────

def _checks_html(name: str, options: List[str]) -> str:
    parts = [
        f'<label><input type="checkbox" name="{name}" value="{html.escape(o)}"> {html.escape(o)}</label>'
        for o in options
    ]
    return "\n".join(parts)


def _radios_html(name: str, options: List[str]) -> str:
    parts = [
        f'<label><input type="radio" name="{name}" value="{html.escape(o)}"> {html.escape(o)}</label>'
        for o in options
    ]
    return "\n".join(parts)


def _fill(template: str, mapping: Dict[str, str]) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def generate_review_html(case: dict, case_num: int, total: int) -> str:
    prev_href = f"../case_{max(1, case_num-1):03d}/review.html"
    next_href = f"../case_{min(total, case_num+1):03d}/review.html"
    prev_disabled = "" if case_num > 1 else 'style="visibility:hidden"'
    next_disabled = "" if case_num < total else 'style="visibility:hidden"'

    nt = case["no_telemetry"]; tg = case["telegen"]
    nt_eval = _read_eval(nt["eval_path"]); tg_eval = _read_eval(tg["eval_path"])
    nt_traj = _trajectory_html(nt["trajectory_path"]); tg_traj = _trajectory_html(tg["trajectory_path"])

    mapping = {
        "CASE_ID": f"case_{case_num:03d}",
        "SAMPLE_NO": str(case.get("sample_id", case_num)),
        "PROJECT_ID": html.escape(case["project_id"]),
        "TASK_ID": html.escape(case["task_id"]),
        "TASK_DESC": html.escape(case.get("task_description", "")),
        "EXPECTED": html.escape(case.get("expected_result", "")),
        "CATEGORY": html.escape(case.get("task_category", "")),
        "SUBCAT": (" / " + html.escape(case["task_subcategories"])) if case.get("task_subcategories") else "",
        "TOTAL_CASES": str(total),
        "PREV_HREF": prev_href, "NEXT_HREF": next_href,
        "PREV_DISABLED": prev_disabled, "NEXT_DISABLED": next_disabled,
        "NT_TRAJECTORY": nt_traj, "TG_TRAJECTORY": tg_traj,
        "NT_STEP_COUNT": str(nt_traj.count('class="step-num"')),
        "TG_STEP_COUNT": str(tg_traj.count('class="step-num"')),
        "NT_GALLERY": _gallery_html(nt["task_dir"], "nt"),
        "TG_GALLERY": _gallery_html(tg["task_dir"], "tg"),
        "NT_FINAL": _final_html(nt["task_dir"], "nt"),
        "TG_FINAL": _final_html(tg["task_dir"], "tg"),
        "NT_VERDICT": html.escape(nt_eval["verdict"] or nt.get("verdict", "")),
        "TG_VERDICT": html.escape(tg_eval["verdict"] or tg.get("verdict", "")),
        "NT_ANSWER": html.escape(nt_eval["answer"] or "Not available."),
        "TG_ANSWER": html.escape(tg_eval["answer"] or "Not available."),
        "NT_EVAL": html.escape(nt_eval["evaluator_response"] or "Not available."),
        "TG_EVAL": html.escape(tg_eval["evaluator_response"] or "Not available."),
        "NT_SOURCE": html.escape(nt.get("app_source_path", "")),
        "TG_SOURCE": html.escape(tg.get("app_source_path", "")),
        "V1_SOURCE": html.escape(case.get("v1_clean_path", "")),
        "JUDGEABILITY_TYPES_HTML": _checks_html("judgeability_types", JUDGEABILITY_TYPES),
        "SHORTCUT_INDICATORS_HTML": _checks_html("shortcut_indicators", SHORTCUT_INDICATORS),
        "CLASSIFICATIONS_HTML": _radios_html("primary_classification", CLASSIFICATIONS),
        "ANNOTATION_VERSION": ANNOTATION_VERSION,
        "LS_KEY": LOCALSTORAGE_KEY,
        "EXPORT_FIELDS_JSON": json.dumps(EXPORT_FIELDS),
    }
    return _fill(REVIEW_TEMPLATE, mapping)


def build_package(cases: List[dict], output: Path, seed: int, force: bool) -> None:
    # Do NOT rmtree the whole output dir: it may hold the input dataset JSON.
    # Only reset the generated cases/ subtree.
    output.mkdir(parents=True, exist_ok=True)
    cases_root = output / "cases"
    if cases_root.exists():
        if not force:
            sys.exit(f"ERROR: {cases_root} exists. Use --force to overwrite.")
        shutil.rmtree(cases_root)
    cases_root.mkdir(parents=True, exist_ok=True)
    total = len(cases)

    # per-case dirs
    case_ids: List[str] = []
    for i, case in enumerate(cases, 1):
        case_id = f"case_{i:03d}"
        case_ids.append(case_id)
        case_dir = output / "cases" / case_id
        ss_dir = case_dir / "screenshots"
        ss_dir.mkdir(parents=True, exist_ok=True)

        # metadata
        meta = {
            "case_id": case_id,
            "sample_id": case.get("sample_id", i),
            "project_id": case["project_id"],
            "task_id": case["task_id"],
            "task_description": case.get("task_description", ""),
            "expected_result": case.get("expected_result", ""),
            "task_category": case.get("task_category", ""),
            "annotation_version": ANNOTATION_VERSION,
            "no_telemetry": case["no_telemetry"],
            "telegen": case["telegen"],
            "v1_clean_path": case.get("v1_clean_path", ""),
            "instrumented_path": case.get("instrumented_path", ""),
        }
        (case_dir / "case_metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # screenshots (version-prefixed symlinks)
        _symlink_screenshots(case["no_telemetry"]["task_dir"], ss_dir, "nt")
        _symlink_screenshots(case["telegen"]["task_dir"], ss_dir, "tg")

        # source_paths.md
        src = f"""# Source Paths - {case_id}

**No-Telemetry app source:** `{case['no_telemetry']['app_source_path']}`
**No-Telemetry task dir:** `{case['no_telemetry']['task_dir']}`

**TeleGen app source:** `{case['telegen']['app_source_path']}`
**TeleGen task dir:** `{case['telegen']['task_dir']}`

**v1 (original) source:** `{case.get('v1_clean_path','')}`
**Instrumented source:** `{case.get('instrumented_path','')}`
"""
        (case_dir / "source_paths.md").write_text(src, encoding="utf-8")

        # review.html
        (case_dir / "review.html").write_text(
            generate_review_html(case, i, total), encoding="utf-8"
        )

    # index.html
    cards = "\n".join(
        f'<a class="card pending" href="cases/{cid}/review.html" data-case-id="{cid}">'
        f'<div class="id">{cid}</div>'
        f'<div class="status">Not yet reviewed</div></a>'
        for cid in case_ids
    )
    index_html = _fill(INDEX_TEMPLATE, {
        "TOTAL_CASES": str(total),
        "SEED": str(seed),
        "ANNOTATION_VERSION": ANNOTATION_VERSION,
        "LS_KEY": LOCALSTORAGE_KEY,
        "CARDS": cards,
        "CASE_IDS_JSON": json.dumps(case_ids),
        "CLASSIFICATIONS_JSON": json.dumps(CLASSIFICATIONS),
        "EXPORT_FIELDS_JSON": json.dumps(EXPORT_FIELDS),
    })
    (output / "index.html").write_text(index_html, encoding="utf-8")

    # empty annotation_template.csv (manual-fill fallback, new schema)
    with open(output / "annotation_template.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        w.writeheader()
        for i, case in enumerate(cases, 1):
            w.writerow({
                "sample_id": case.get("sample_id", i),
                "project_id": case["project_id"],
                "task_id": case["task_id"],
                "annotation_version": ANNOTATION_VERSION,
            })

    print(f"Built {total} cases at {output}")
    print(f"  index: {output / 'index.html'}")
    print(f"  annotation_template: {output / 'annotation_template.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build TeleGen usability-audit annotation package")
    ap.add_argument("--cases", required=True, help="Path to the 30-case (or example) JSON dataset.")
    ap.add_argument("--output", required=True, help="Output directory.")
    ap.add_argument("--workspace", default=".", help="Workspace root (for symlink boundary checks).")
    ap.add_argument("--force", action="store_true", help="Overwrite existing output.")
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    bhp._WORKSPACE_ROOT = workspace  # reuse existing global used by safe_symlink

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = data["cases"]
    if len(cases) != 30 and not args.cases.endswith("example_cases.json"):
        # real dataset must be exactly 30; example may differ
        if len(cases) != 2:
            sys.exit(f"ERROR: expected 30 cases (or 2 for example), got {len(cases)}")
    # integrity checks
    for c in cases:
        for k in ("project_id", "task_id", "no_telemetry", "telegen"):
            if k not in c:
                sys.exit(f"ERROR: case missing {k}: {c}")
        for v in ("no_telemetry", "telegen"):
            for pk in ("task_dir", "eval_path", "trajectory_path", "app_source_path"):
                if pk not in c[v]:
                    sys.exit(f"ERROR: case {c.get('project_id')} missing {v}.{pk}")

    build_package(cases, Path(args.output).resolve(), data.get("random_seed", 20260714), args.force)


if __name__ == "__main__":
    main()
