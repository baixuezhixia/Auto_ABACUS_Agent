from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskType(str, Enum):
    SCF = "scf"
    RELAX = "relax"
    BANDS = "bands"
    DOS = "dos"
    ELASTIC = "elastic"


@dataclass
class CalcTask:
    task_id: str
    task_type: TaskType
    description: str
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    task_id: str
    task_type: str
    work_dir: str
    return_code: int
    stdout_tail: str
    stderr_tail: str
    status: str
    artifacts: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructureArtifact:
    source: str
    input: str
    material_id: str
    formula: str
    cif_path: str
    lattice_type: str
    candidates: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PipelineResult:
    query: str
    tasks: List[CalcTask]
    execution: List[ExecutionResult]
    summary: str
    report_path: Optional[str] = None
    structure_artifact: Optional[StructureArtifact] = None
    notices: List[str] = field(default_factory=list)
