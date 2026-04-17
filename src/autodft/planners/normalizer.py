"""Workflow task normalization and dependency completion.

This module owns the phase-1 dependency conventions shared by all planners:
task ordering, generated task IDs, and required upstream tasks.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

from autodft.core.enums import BasisType, TaskType
from autodft.core.models import TaskNode, WorkflowSpec


TASK_ORDER = [
    TaskType.RELAX,
    TaskType.SCF,
    TaskType.BANDS,
    TaskType.DOS,
    TaskType.ELASTIC,
]


def normalize_workflow(
    query: str,
    tasks: Sequence[TaskNode],
    workflow_id: Optional[str] = None,
) -> WorkflowSpec:
    """Return a normalized ``WorkflowSpec`` from inferred task nodes.

    Duplicate task types are collapsed for phase 1 to match the current
    prototype's single-pass workflow behavior. Required dependency tasks are
    inserted before ordering and ID assignment.
    """

    ordered_sources = _complete_required_tasks(_dedupe_by_task_type(tasks), query=query)

    normalized_tasks: List[TaskNode] = []
    ids_by_type: Dict[TaskType, str] = {}
    basis_type = _first_basis_type(tasks)

    for source in ordered_sources:
        task_type = source.task_type

        task_id = f"t{len(normalized_tasks) + 1}_{task_type.value}"
        depends_on = _dependencies_for(task_type, ids_by_type)
        resolved_basis_type = source.basis_type or basis_type
        normalized_tasks.append(
            TaskNode(
                task_id=task_id,
                task_type=task_type,
                description=source.description or default_description(task_type),
                depends_on=depends_on,
                params=_params_with_basis_and_relax_mode(source.params, resolved_basis_type, task_type, query),
                basis_type=resolved_basis_type,
                status=source.status,
            )
        )
        ids_by_type[task_type] = task_id

    return WorkflowSpec(
        workflow_id=workflow_id or "workflow",
        query=query,
        tasks=normalized_tasks,
    )


def task_node_from_type(
    task_type: TaskType,
    *,
    description: str = "",
    params: Optional[Dict[str, object]] = None,
    basis_type: Optional[BasisType] = None,
) -> TaskNode:
    """Create an unnormalized task node for planner output."""

    return TaskNode(
        task_id="",
        task_type=task_type,
        description=description or default_description(task_type),
        params=dict(params or {}),
        basis_type=basis_type,
    )


def default_description(task_type: TaskType) -> str:
    """Return the current prototype's default task description."""

    descriptions = {
        TaskType.RELAX: "Run structural relaxation",
        TaskType.SCF: "Run self-consistent electronic structure calculation",
        TaskType.BANDS: "Run band structure calculation on converged charge",
        TaskType.DOS: "Run density of states calculation on converged charge",
        TaskType.ELASTIC: "Run elastic properties workflow",
    }
    return descriptions[task_type]


def _dedupe_by_task_type(tasks: Iterable[TaskNode]) -> List[TaskNode]:
    seen: set[TaskType] = set()
    ordered: List[TaskNode] = []
    for task in tasks:
        if task.task_type not in seen:
            seen.add(task.task_type)
            ordered.append(task)
    return ordered


def _complete_required_tasks(tasks: List[TaskNode], *, query: str) -> List[TaskNode]:
    if not tasks:
        return [task_node_from_type(TaskType.SCF)]

    completed = list(tasks)
    present = {task.task_type for task in completed}
    basis_type = _first_basis_type(completed)

    if TaskType.ELASTIC in present and TaskType.RELAX not in present:
        _insert_before_first(
            completed,
            task_node_from_type(TaskType.RELAX, params=_relax_mode_params(query), basis_type=basis_type),
            {TaskType.ELASTIC},
        )
        present.add(TaskType.RELAX)

    needs_scf = any(task.task_type in {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC} for task in completed)
    if needs_scf and TaskType.SCF not in present:
        _insert_before_first(
            completed,
            task_node_from_type(TaskType.SCF, basis_type=basis_type),
            {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC},
        )

    return completed


def _insert_before_first(tasks: List[TaskNode], inserted: TaskNode, target_types: set[TaskType]) -> None:
    for index, task in enumerate(tasks):
        if task.task_type in target_types:
            tasks.insert(index, inserted)
            return
    tasks.append(inserted)


def _dependencies_for(task_type: TaskType, ids_by_type: Dict[TaskType, str]) -> List[str]:
    if task_type == TaskType.SCF and TaskType.RELAX in ids_by_type:
        return [ids_by_type[TaskType.RELAX]]
    if task_type in {TaskType.BANDS, TaskType.DOS} and TaskType.SCF in ids_by_type:
        return [ids_by_type[TaskType.SCF]]
    if task_type == TaskType.ELASTIC:
        if TaskType.SCF in ids_by_type:
            return [ids_by_type[TaskType.SCF]]
        if TaskType.RELAX in ids_by_type:
            return [ids_by_type[TaskType.RELAX]]
    return []


def _first_basis_type(tasks: Sequence[TaskNode]) -> Optional[BasisType]:
    for task in tasks:
        if task.basis_type is not None:
            return task.basis_type
    return None


def _params_with_basis(params: Dict[str, object], basis_type: Optional[BasisType]) -> Dict[str, object]:
    merged = dict(params)
    if basis_type is not None:
        merged.setdefault("basis_type", basis_type.value)
    return merged


def _params_with_basis_and_relax_mode(
    params: Dict[str, object],
    basis_type: Optional[BasisType],
    task_type: TaskType,
    query: str,
) -> Dict[str, object]:
    merged = _params_with_basis(params, basis_type)
    if task_type == TaskType.RELAX and _detect_full_relax(query):
        merged.setdefault("calculation", "cell-relax")
    return merged


def _relax_mode_params(query: str) -> Dict[str, object]:
    if _detect_full_relax(query):
        return {"calculation": "cell-relax"}
    return {}


def _detect_full_relax(query: str) -> bool:
    return re.search(r"\bfully\s+relax\b", query, re.IGNORECASE) is not None


__all__ = [
    "TASK_ORDER",
    "default_description",
    "normalize_workflow",
    "task_node_from_type",
]
