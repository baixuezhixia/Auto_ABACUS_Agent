"""Machine-readable JSON report assembly and serialization."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from autodft.core.models import RunSummary


def build_json_report(summary: RunSummary) -> dict[str, Any]:
    """Build a stable machine-readable report payload.

    The shape keeps the important fields from the legacy report: query,
    structure, notices, planned tasks, execution records, and report path.
    """

    workflow = summary.workflow
    structure = workflow.structure
    return {
        "query": workflow.query,
        "workflow_id": workflow.workflow_id,
        "status": summary.status.value,
        "structure": to_jsonable(structure) if structure is not None else None,
        "notices": list(summary.notices),
        "report_path": summary.report_path,
        "tasks": [
            {
                "task_id": task.task_id,
                "task_type": task.task_type.value,
                "description": task.description,
                "depends_on": list(task.depends_on),
                "params": dict(task.params),
                "basis_type": task.basis_type.value if task.basis_type else None,
                "status": task.status.value,
            }
            for task in workflow.tasks
        ],
        "execution": [
            {
                "task_id": record.task_id,
                "task_type": record.task_type.value,
                "status": record.status.value,
                "return_code": record.return_code,
                "work_dir": record.work_dir,
                "artifacts": to_jsonable(record.artifacts),
                "metrics": to_jsonable(record.metrics),
                "stdout_tail": record.stdout_tail,
                "stderr_tail": record.stderr_tail,
                "started_at": record.started_at,
                "finished_at": record.finished_at,
            }
            for record in summary.executions
        ],
        "metadata": to_jsonable(summary.metadata),
    }


def write_json_report(summary: RunSummary, output_path: str | Path) -> Path:
    """Serialize a run summary to the current JSON report style."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary.report_path = str(output_path)
    payload = build_json_report(summary)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses and enums into JSON-compatible values."""

    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


__all__ = ["build_json_report", "to_jsonable", "write_json_report"]
