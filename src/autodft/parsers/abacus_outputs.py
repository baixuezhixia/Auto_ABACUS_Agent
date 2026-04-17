"""Backward-compatible ABACUS output parser function."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from autodft.core.enums import TaskType
from autodft.parsers.abacus_log_parser import AbacusLogParser


def parse_abacus_result(task_type: TaskType, task_dir: str | Path, task_id: str) -> Dict[str, Any]:
    """Parse the current prototype's basic ABACUS result metrics."""

    return AbacusLogParser().parse_task(task_type, Path(task_dir), task_id)


__all__ = ["parse_abacus_result"]
