"""Parser interfaces for execution records and output artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from autodft.core.models import TaskExecutionRecord


class TaskResultParser(ABC):
    """Base parser for one completed task execution record."""

    @abstractmethod
    def parse(self, record: TaskExecutionRecord) -> Dict[str, Any]:
        """Return parsed metrics for a task execution record."""


__all__ = ["TaskResultParser"]

