"""Human-readable run summary report."""

from __future__ import annotations

from pathlib import Path
from typing import List

from autodft.core.models import RunSummary


def build_summary_text(summary: RunSummary) -> str:
    """Build a concise human-readable summary for CLI output."""

    workflow = summary.workflow
    total = len(summary.executions)
    success = sum(1 for record in summary.executions if record.status.value == "success")
    failed = sum(1 for record in summary.executions if record.status.value == "failed")
    lines: List[str] = [
        f"Workflow {workflow.workflow_id}: {summary.status.value}",
        f"Query: {workflow.query}",
        f"Tasks: {total} executed, {success} success, {failed} failed",
    ]
    if workflow.structure is not None:
        lines.append(f"Structure: {workflow.structure.structure_id} ({workflow.structure.formula})")
    if summary.report_path:
        lines.append(f"Report: {summary.report_path}")
    if summary.notices:
        lines.append("Notices:")
        lines.extend(f"- {notice}" for notice in summary.notices)

    for record in summary.executions:
        metric_bits = []
        if record.metrics.get("converged") is not None:
            metric_bits.append(f"converged={record.metrics.get('converged')}")
        if record.metrics.get("total_energy_ev") is not None:
            metric_bits.append(f"energy_ev={record.metrics.get('total_energy_ev')}")
        suffix = f" ({', '.join(metric_bits)})" if metric_bits else ""
        lines.append(f"- {record.task_id} {record.task_type.value}: {record.status.value}{suffix}")
    return "\n".join(lines)


def write_summary_report(summary: RunSummary, output_path: str | Path) -> Path:
    """Write a human-readable summary report to disk."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_summary_text(summary) + "\n", encoding="utf-8")
    return output_path


__all__ = ["build_summary_text", "write_summary_report"]
