"""Rule-based planner for simple ABACUS workflow queries."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from autodft.core.enums import BasisType, TaskType
from autodft.core.models import TaskNode, WorkflowSpec
from autodft.planners.base import WorkflowPlanner
from autodft.planners.normalizer import normalize_workflow, task_node_from_type


_PATTERNS = {
    TaskType.SCF: [
        r"\bscf\b",
        r"\u81ea\u6d3d",
        r"self\s*consistent",
    ],
    TaskType.RELAX: [
        r"\brelax\b",
        r"\u5f1b\u8c6b",
        r"\u7ed3\u6784\u4f18\u5316",
        r"cell\s*relax",
    ],
    TaskType.BANDS: [
        r"\bbands?\b",
        r"\bband\s*structure\b",
        r"\u80fd\u5e26",
    ],
    TaskType.DOS: [
        r"\bdos\b",
        r"density\s+of\s+states",
        r"\u6001\u5bc6\u5ea6",
    ],
    TaskType.ELASTIC: [
        r"\belastic\b",
        r"\u5f39\u6027",
        r"elastic\s+properties",
    ],
}

_TOKEN_BOUNDARY = r"[A-Za-z0-9_]"


class RulePlanner(WorkflowPlanner):
    """Infer a workflow from query keywords and normalize dependencies."""

    def plan(self, query: str, workflow_id: Optional[str] = None) -> WorkflowSpec:
        """Decode a query with deterministic rules and return a workflow spec."""

        tasks = infer_task_nodes(query)
        return normalize_workflow(query=query, tasks=tasks, workflow_id=workflow_id)


def infer_task_nodes(query: str) -> List[TaskNode]:
    """Infer unnormalized task nodes from a query.

    This function intentionally performs only keyword inference. Required task
    insertion, ordering, IDs, and dependencies are handled by ``normalizer``.
    """

    text = query.strip()
    basis_type = detect_basis_type(text)
    full_relax = detect_full_relax(text)
    task_types = _task_types_by_query_order(text)

    if not task_types:
        task_types = [TaskType.SCF]

    return [
        task_node_from_type(
            task_type,
            params=_default_params(task_type, basis_type, full_relax),
            basis_type=basis_type,
        )
        for task_type in task_types
    ]


def detect_basis_type(text: str) -> Optional[BasisType]:
    """Detect an explicit basis hint from query text."""

    lowered = text.lower()
    if _contains_token(lowered, "lcao"):
        return BasisType.LCAO
    if _contains_token(lowered, "pw"):
        return BasisType.PW
    return None


def detect_full_relax(text: str) -> bool:
    """Return whether the query explicitly asks for full cell relaxation."""

    return re.search(r"\bfully\s+relax\b", text, re.IGNORECASE) is not None


def _default_params(task_type: TaskType, basis_type: Optional[BasisType], full_relax: bool = False) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if basis_type is not None:
        params["basis_type"] = basis_type.value
    if task_type == TaskType.RELAX and full_relax:
        params["calculation"] = "cell-relax"
    if task_type == TaskType.BANDS:
        params["kline_mode"] = "high_symmetry"
    if task_type == TaskType.DOS:
        params["dos_mode"] = "total"
    if task_type == TaskType.ELASTIC:
        params["strain_set"] = "small_deformation"
    return params


def _task_types_by_query_order(text: str) -> List[TaskType]:
    matches = []
    pattern_order = {task_type: index for index, task_type in enumerate(_PATTERNS)}
    for task_type, patterns in _PATTERNS.items():
        positions = [match.start() for pattern in patterns for match in re.finditer(pattern, text, re.IGNORECASE)]
        if positions:
            matches.append((min(positions), pattern_order[task_type], task_type))
    return _ordered_unique(task_type for _, _, task_type in sorted(matches))


def _contains_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _ordered_unique(task_types) -> List[TaskType]:
    seen = set()
    out: List[TaskType] = []
    for task_type in task_types:
        if task_type not in seen:
            seen.add(task_type)
            out.append(task_type)
    return out


def _contains_token(text: str, token: str) -> bool:
    pattern = rf"(?<!{_TOKEN_BOUNDARY}){re.escape(token)}(?!{_TOKEN_BOUNDARY})"
    return re.search(pattern, text, re.IGNORECASE) is not None


__all__ = [
    "RulePlanner",
    "detect_basis_type",
    "detect_full_relax",
    "infer_task_nodes",
]
