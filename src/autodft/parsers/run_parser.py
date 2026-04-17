"""Execution-record parser that separates status/metrics from reporting."""

from __future__ import annotations

from typing import Any, Dict

from autodft.core.enums import TaskStatus
from autodft.core.models import TaskExecutionRecord
from autodft.parsers.abacus_log_parser import AbacusLogParser
from autodft.parsers.base import TaskResultParser


class RunParser(TaskResultParser):
    """Parse one task execution record after the runner finishes."""

    def __init__(self, log_parser: AbacusLogParser | None = None) -> None:
        self.log_parser = log_parser or AbacusLogParser()

    def parse(self, record: TaskExecutionRecord) -> Dict[str, Any]:
        """Return parsed metrics and normalized execution status fields."""

        metrics = self.log_parser.parse_task(record.task_type, record.work_dir, record.task_id)
        metrics["return_code"] = record.return_code
        metrics["runner_status"] = record.status.value
        metrics["execution_ok"] = record.return_code == 0 and record.status == TaskStatus.SUCCESS
        return metrics

    def update_record(self, record: TaskExecutionRecord) -> TaskExecutionRecord:
        """Merge parsed metrics into an execution record."""

        record.metrics.update(self.parse(record))
        return record


__all__ = ["RunParser"]

