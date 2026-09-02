#!/usr/bin/env python3
"""Analyze human annotations against WebVoyager judgments.

Usage:
    python scripts/analyze_human_annotations.py \
        --annotations human_validation_telegen/annotation_template.csv \
        --unblinded-manifest human_validation_telegen/selected_cases_unblinded.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def wilson_ci(successes: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score 95% confidence interval."""
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def load_annotations(path: Path) -> List[dict]:
    """Load annotation CSV."""
    rows: List[dict] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_manifest(path: Path) -> Dict[str, dict]:
    """Load unblinded manifest, keyed by case_id."""
    result: Dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            result[row["case_id"]] = row
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze human annotations against WV judgments"
    )
    parser.add_argument(
        "--annotations",
        required=True,
        help="Path to annotation_template.csv (filled in by reviewer).",
    )
    parser.add_argument(
        "--unblinded-manifest",
        required=True,
        help="Path to selected_cases_unblinded.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for analysis files (default: alongside annotations).",
    )

    args = parser.parse_args()

    ann_path = Path(args.annotations)
    manifest_path = Path(args.unblinded_manifest)

    if not ann_path.exists():
        sys.exit(f"ERROR: Annotations file not found: {ann_path}")
    if not manifest_path.exists():
        sys.exit(f"ERROR: Manifest file not found: {manifest_path}")

    annotations = load_annotations(ann_path)
    manifest = load_manifest(manifest_path)

    # Determine output directory
    output_dir = Path(args.output_dir) if args.output_dir else ann_path.parent / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Merge annotations with manifest ────────────────────────────
    merged: List[dict] = []
    for ann in annotations:
        case_id = ann.get("case_id", "")
        man = manifest.get(case_id, {})
        human_verdict = ann.get("human_verdict", "").strip()
        if not human_verdict:
            continue  # Skip unannotated cases
        wv_verdict = man.get("wv_verdict", "").strip()
        merged.append({
            "case_id": case_id,
            "project_id": man.get("project_id", ""),
            "task_id": man.get("task_id", ""),
            "task_category": man.get("task_category", ""),
            "wv_verdict": wv_verdict,
            "human_verdict": human_verdict,
            "human_confidence": ann.get("human_confidence", "").strip(),
            "trajectory_valid": ann.get("trajectory_valid", "").strip(),
            "failure_type": ann.get("failure_type", "").strip(),
            "evidence_step": ann.get("evidence_step", "").strip(),
            "evidence_screenshot": ann.get("evidence_screenshot", "").strip(),
            "annotation_reason": ann.get("annotation_reason", "").strip(),
            "annotator_id": ann.get("annotator_id", "").strip(),
            "needs_second_review": ann.get("needs_second_review", "").strip(),
        })

    total_annotated = len(merged)
    if total_annotated == 0:
        print("No annotated cases found. Fill in human_verdict in the annotation CSV.")
        return

    # ── Compute agreement ──────────────────────────────────────────
    success_cases = [m for m in merged if m["wv_verdict"] == "Success"]
    failure_cases = [m for m in merged if m["wv_verdict"] == "Failure"]

    # Success-case agreement: human agrees with WV-success
    succ_agree = sum(1 for m in success_cases if m["human_verdict"] == "Success")
    succ_total = len(success_cases)
    succ_agreement = succ_agree / succ_total if succ_total > 0 else 0.0

    # Failure-case agreement: human agrees with WV-failure
    fail_agree = sum(1 for m in failure_cases if m["human_verdict"] == "Failure")
    fail_total = len(failure_cases)
    fail_agreement = fail_agree / fail_total if fail_total > 0 else 0.0

    # Balanced agreement
    total_agree = succ_agree + fail_agree
    balanced_agreement = total_agree / total_annotated if total_annotated > 0 else 0.0

    # WV false positives: WV Success, Human Failure
    false_positives = [m for m in success_cases if m["human_verdict"] == "Failure"]

    # WV false negatives: WV Failure, Human Success
    false_negatives = [m for m in failure_cases if m["human_verdict"] == "Success"]

    # Unclear cases
    unclear_cases = [m for m in merged if m["human_verdict"] == "Unclear"]

    # Wilson CIs
    succ_ci = wilson_ci(succ_agree, succ_total)
    fail_ci = wilson_ci(fail_agree, fail_total)
    balanced_ci = wilson_ci(total_agree, total_annotated)

    # Weighted estimate (based on observed TeleGen class distribution)
    w_success = 493 / 647
    w_failure = 154 / 647
    # For weighted estimate, treat Unclear as non-agreement
    succ_eff_agree = succ_agree
    succ_eff_total = succ_total
    fail_eff_agree = fail_agree
    fail_eff_total = fail_total
    succ_eff_rate = succ_eff_agree / succ_eff_total if succ_eff_total > 0 else 0
    fail_eff_rate = fail_eff_agree / fail_eff_total if fail_eff_total > 0 else 0
    weighted_agreement = w_success * succ_eff_rate + w_failure * fail_eff_rate

    # ── Breakdowns ────────────────────────────────────────────────
    failure_type_dist = Counter(m["failure_type"] for m in merged if m["failure_type"])
    confidence_dist = Counter(m["human_confidence"] for m in merged if m["human_confidence"])
    trajectory_valid_dist = Counter(m["trajectory_valid"] for m in merged if m["trajectory_valid"])

    # ── Confusion matrix ──────────────────────────────────────────
    # Rows: WV verdict, Columns: Human verdict
    confusion = defaultdict(lambda: defaultdict(int))
    for m in merged:
        confusion[m["wv_verdict"]][m["human_verdict"]] += 1

    # ── Disagreement cases ────────────────────────────────────────
    disagreements = [m for m in merged if m["human_verdict"] != m["wv_verdict"]]

    # ── Generate outputs ──────────────────────────────────────────

    # Summary Markdown
    summary_md = f"""# Human Validation Analysis Summary

## Overview

- **Annotated cases:** {total_annotated} / 60
- **WV-Success cases annotated:** {succ_total} / 30
- **WV-Failure cases annotated:** {fail_total} / 30

## Agreement Rates

| Metric | Agreement | Count | Wilson 95% CI |
|--------|-----------|-------|---------------|
| Success-case (WV=Success) | {succ_agreement:.1%} | {succ_agree}/{succ_total} | [{succ_ci[0]:.1%}, {succ_ci[1]:.1%}] |
| Failure-case (WV=Failure) | {fail_agreement:.1%} | {fail_agree}/{fail_total} | [{fail_ci[0]:.1%}, {fail_ci[1]:.1%}] |
| Balanced agreement | {balanced_agreement:.1%} | {total_agree}/{total_annotated} | [{balanced_ci[0]:.1%}, {balanced_ci[1]:.1%}] |

**Note:** The balanced agreement is computed on the 30+30 balanced sample,
not the natural 493/154 distribution. Do not label it as overall WV accuracy.

### Weighted Estimate (Distribution-Adjusted)

Based on the observed TeleGen class distribution (493 success / 154 failure / 647 total):

    weighted_agreement = (493/647) × {succ_eff_rate:.1%} + (154/647) × {fail_eff_rate:.1%}
                       = {weighted_agreement:.1%}

**This is a weighted estimate based on the observed TeleGen class distribution, not a direct measurement.**

## Error Analysis

| Error Type | Count | Description |
|------------|-------|-------------|
| WV False Positives (WV=Success, Human=Failure) | {len(false_positives)} | WV said success, human disagrees |
| WV False Negatives (WV=Failure, Human=Success) | {len(false_negatives)} | WV said failure, human disagrees |
| Unclear cases | {len(unclear_cases)} | Human could not determine |

## Confusion Matrix

| | Human=Success | Human=Failure | Human=Unclear | Total |
|---|---|---|---|---|
| WV=Success | {confusion['Success']['Success']} | {confusion['Success']['Failure']} | {confusion['Success']['Unclear']} | {sum(confusion['Success'].values())} |
| WV=Failure | {confusion['Failure']['Success']} | {confusion['Failure']['Failure']} | {confusion['Failure']['Unclear']} | {sum(confusion['Failure'].values())} |
| Total | {confusion['Success']['Success'] + confusion['Failure']['Success']} | {confusion['Success']['Failure'] + confusion['Failure']['Failure']} | {confusion['Success']['Unclear'] + confusion['Failure']['Unclear']} | {total_annotated} |

## Failure-Type Breakdown

| Failure Type | Count |
|-------------|-------|
"""
    for ft, cnt in sorted(failure_type_dist.items(), key=lambda x: -x[1]):
        summary_md += f"| {ft} | {cnt} |\n"

    summary_md += f"""
## Confidence-Level Breakdown

| Confidence | Count |
|-----------|-------|
"""
    for conf, cnt in sorted(confidence_dist.items(), key=lambda x: -x[1]):
        summary_md += f"| {conf} | {cnt} |\n"

    summary_md += f"""
## Trajectory Validity Breakdown

| Trajectory Valid | Count |
|-----------------|-------|
"""
    for tv, cnt in sorted(trajectory_valid_dist.items(), key=lambda x: -x[1]):
        summary_md += f"| {tv} | {cnt} |\n"

    summary_md += f"""
## Disagreement Cases

{len(disagreements)} disagreement(s) found.

| Case ID | WV Verdict | Human Verdict | Confidence | Failure Type | Reason |
|---------|-----------|---------------|------------|-------------|--------|
"""
    for d in disagreements:
        reason = d["annotation_reason"][:80] + "..." if len(d["annotation_reason"]) > 80 else d["annotation_reason"]
        summary_md += f"| {d['case_id']} | {d['wv_verdict']} | {d['human_verdict']} | {d['human_confidence']} | {d['failure_type']} | {reason} |\n"

    (output_dir / "human_validation_summary.md").write_text(summary_md, encoding="utf-8")

    # Summary CSV
    summary_csv = output_dir / "human_validation_summary.csv"
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value", "count", "wilson_ci_low", "wilson_ci_high"])
        writer.writerow(["success_case_agreement", f"{succ_agreement:.4f}", f"{succ_agree}/{succ_total}", f"{succ_ci[0]:.4f}", f"{succ_ci[1]:.4f}"])
        writer.writerow(["failure_case_agreement", f"{fail_agreement:.4f}", f"{fail_agree}/{fail_total}", f"{fail_ci[0]:.4f}", f"{fail_ci[1]:.4f}"])
        writer.writerow(["balanced_agreement", f"{balanced_agreement:.4f}", f"{total_agree}/{total_annotated}", f"{balanced_ci[0]:.4f}", f"{balanced_ci[1]:.4f}"])
        writer.writerow(["weighted_agreement", f"{weighted_agreement:.4f}", "", "", ""])
        writer.writerow(["wv_false_positives", "", str(len(false_positives)), "", ""])
        writer.writerow(["wv_false_negatives", "", str(len(false_negatives)), "", ""])
        writer.writerow(["unclear_cases", "", str(len(unclear_cases)), "", ""])
        writer.writerow(["total_annotated", "", str(total_annotated), "", ""])

    # Confusion matrix CSV
    conf_csv = output_dir / "confusion_matrix.csv"
    with open(conf_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["wv_verdict", "human_success", "human_failure", "human_unclear", "total"])
        for wv in ["Success", "Failure"]:
            row = [wv]
            for hv in ["Success", "Failure", "Unclear"]:
                row.append(confusion[wv][hv])
            row.append(sum(confusion[wv].values()))
            writer.writerow(row)

    # Disagreement cases CSV
    dis_csv = output_dir / "disagreement_cases.csv"
    with open(dis_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "case_id", "project_id", "task_id", "wv_verdict", "human_verdict",
            "human_confidence", "failure_type", "evidence_step",
            "evidence_screenshot", "annotation_reason", "annotator_id",
        ])
        for d in disagreements:
            writer.writerow([
                d["case_id"], d["project_id"], d["task_id"],
                d["wv_verdict"], d["human_verdict"], d["human_confidence"],
                d["failure_type"], d["evidence_step"], d["evidence_screenshot"],
                d["annotation_reason"], d["annotator_id"],
            ])

    # Print summary
    print("\n" + "=" * 60)
    print("HUMAN VALIDATION ANALYSIS")
    print("=" * 60)
    print(f"Annotated cases: {total_annotated} / 60")
    print(f"WV-Success annotated: {succ_total} / 30")
    print(f"WV-Failure annotated: {fail_total} / 30")
    print()
    print(f"Success-case agreement: {succ_agreement:.1%} ({succ_agree}/{succ_total})")
    print(f"  Wilson 95% CI: [{succ_ci[0]:.1%}, {succ_ci[1]:.1%}]")
    print(f"Failure-case agreement: {fail_agreement:.1%} ({fail_agree}/{fail_total})")
    print(f"  Wilson 95% CI: [{fail_ci[0]:.1%}, {fail_ci[1]:.1%}]")
    print(f"Balanced agreement: {balanced_agreement:.1%} ({total_agree}/{total_annotated})")
    print(f"  Wilson 95% CI: [{balanced_ci[0]:.1%}, {balanced_ci[1]:.1%}]")
    print()
    print(f"Weighted estimate (493/154 distribution): {weighted_agreement:.1%}")
    print(f"  (labeled as weighted estimate, not direct measurement)")
    print()
    print(f"WV false positives: {len(false_positives)}")
    print(f"WV false negatives: {len(false_negatives)}")
    print(f"Unclear cases: {len(unclear_cases)}")
    print()
    print("Output files:")
    print(f"  {output_dir / 'human_validation_summary.md'}")
    print(f"  {output_dir / 'human_validation_summary.csv'}")
    print(f"  {output_dir / 'confusion_matrix.csv'}")
    print(f"  {output_dir / 'disagreement_cases.csv'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
