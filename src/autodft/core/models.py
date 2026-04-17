"""Typed workflow, task, structure, execution, and report models.

These dataclasses are the first shared model layer for the phase-1 package.
They are intentionally small and serializable so existing prototype concepts
can move into the new architecture without a large framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .enums import ArtifactType, BasisType, TaskStatus, TaskType


@dataclass
class ArtifactRef:
    """Reference to a file or directory produced or consumed by the workflow.

    Future planners, ABACUS input builders, executors, parsers, and reporters
    will exchange artifacts through this model instead of passing raw path
    strings with implicit meaning.
    """

    artifact_type: ArtifactType
    path: str
    task_id: Optional[str] = None
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructureSource:
    """Original source request for a structure.

    This records what the user or planner asked for before it becomes concrete
    files. For the current repository this is typically a Materials Project
    material ID or formula, but the model leaves room for local files later.
    """

    provider: str
    raw_input: str
    query: str = ""
    source_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedStructure:
    """A structure selected and materialized for workflow use.

    This model replaces the current loose structure artifact shape with a
    source, stable identity fields, candidate metadata, and explicit artifact
    references such as CIF and STRU files.
    """

    source: StructureSource
    structure_id: str
    formula: str
    lattice_type: str = "conventional"
    artifacts: List[ArtifactRef] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskNode:
    """A planned calculation task in a workflow graph.

    Task nodes make the workflow-oriented design explicit: each node has a
    stable ID, a task type, dependency IDs, optional ABACUS parameters, and an
    execution status that can evolve as the orchestrator runs.
    """

    task_id: str
    task_type: TaskType
    description: str = ""
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    basis_type: Optional[BasisType] = None
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class WorkflowSpec:
    """Planned workflow before or during execution.

    The planner will produce this model from a natural-language query, manual
    task list, or future structured request. It keeps task ordering explicit
    while still allowing dependency-aware orchestration.
    """

    workflow_id: str
    query: str
    tasks: List[TaskNode] = field(default_factory=list)
    structure: Optional[ResolvedStructure] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskExecutionRecord:
    """Execution result and parsed artifacts for a single task.

    This is the future equivalent of the current ``ExecutionResult`` model,
    with explicit status and artifact references while preserving practical
    fields such as return code, output tails, and parsed metrics.
    """

    task_id: str
    task_type: TaskType
    status: TaskStatus
    work_dir: str
    return_code: Optional[int] = None
    artifacts: List[ArtifactRef] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    stdout_tail: str = ""
    stderr_tail: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass
class RunSummary:
    """Top-level run result for reporting and API handoff.

    The report layer will serialize this model after workflow execution. It
    groups the planned workflow, resolved structure, per-task records, notices,
    and final report artifact location.
    """

    workflow: WorkflowSpec
    status: TaskStatus
    executions: List[TaskExecutionRecord] = field(default_factory=list)
    report_path: Optional[str] = None
    notices: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ArtifactRef",
    "ResolvedStructure",
    "RunSummary",
    "StructureSource",
    "TaskExecutionRecord",
    "TaskNode",
    "WorkflowSpec",
]
