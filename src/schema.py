#定义数据结构。比如一个任务是什么、执行结果是什么、
#整次 pipeline 结果是什么，都在这里统一成 dataclass

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
class PipelineResult:
    query: str
    tasks: List[CalcTask]
    execution: List[ExecutionResult]
    summary: str
    report_path: Optional[str] = None
