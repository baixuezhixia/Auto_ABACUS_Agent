"""Planner interface for turning user intent into workflow specs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from autodft.core.models import WorkflowSpec


class WorkflowPlanner(ABC):
    """Base class for task planners.

    Planners convert a user query or future structured request into a
    ``WorkflowSpec``. Concrete planners should keep inference concerns separate
    from workflow normalization so dependency policy remains centralized.
    """

    @abstractmethod
    def plan(self, query: str, workflow_id: Optional[str] = None) -> WorkflowSpec:
        """Return a normalized workflow for the provided query."""


__all__ = ["WorkflowPlanner"]

