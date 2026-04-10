
#把自然语言 query 里的关键词拆成具体任务，
#如 scf、relax、bands、dos、elastic，并自动补依赖
from __future__ import annotations

import re
from typing import Dict, List

from schema import CalcTask, TaskType


_PATTERNS = {
    TaskType.SCF: [
        r"\bscf\b",
        r"自洽",
        r"self\s*consistent",
    ],
    TaskType.RELAX: [
        r"\brelax\b",
        r"弛豫",
        r"结构优化",
        r"cell\s*relax",
    ],
    TaskType.BANDS: [
        r"\bband(?:\s*structure)?\b",
        r"能带",
    ],
    TaskType.DOS: [
        r"\bdos\b",
        r"density\s+of\s+states",
        r"态密度",
    ],
    TaskType.ELASTIC: [
        r"elastic",
        r"弹性",
        r"elastic\s+properties",
    ],
}


def _contains_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _ordered_unique(task_types: List[TaskType]) -> List[TaskType]:
    seen = set()
    out: List[TaskType] = []
    for t in task_types:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def decode_tasks(query: str) -> List[CalcTask]:
    text = query.strip()
    detected: List[TaskType] = []

    for ttype, plist in _PATTERNS.items():
        if _contains_any(text, plist):
            detected.append(ttype)

    # If user asks for bands or dos only, add SCF prerequisite.
    if TaskType.BANDS in detected and TaskType.SCF not in detected:
        detected.insert(0, TaskType.SCF)
    if TaskType.DOS in detected and TaskType.SCF not in detected:
        detected.insert(0, TaskType.SCF)

    # Elastic workflow usually needs relaxed structure + SCF baseline.
    if TaskType.ELASTIC in detected:
        if TaskType.RELAX not in detected:
            detected.insert(0, TaskType.RELAX)
        if TaskType.SCF not in detected:
            detected.insert(1, TaskType.SCF)

    detected = _ordered_unique(detected)

    # If nothing detected, default to SCF as the minimal safe baseline.
    if not detected:
        detected = [TaskType.SCF]

    tasks: List[CalcTask] = []
    last_task_id = ""
    for idx, ttype in enumerate(detected, start=1):
        task_id = f"t{idx}_{ttype.value}"
        deps = [last_task_id] if last_task_id else []
        description = _default_description(ttype)
        tasks.append(
            CalcTask(
                task_id=task_id,
                task_type=ttype,
                description=description,
                depends_on=deps,
                params=_default_params(ttype),
            )
        )
        last_task_id = task_id

    return tasks


def _default_description(task_type: TaskType) -> str:
    mapping: Dict[TaskType, str] = {
        TaskType.SCF: "Run self-consistent electronic structure calculation",
        TaskType.RELAX: "Run structural relaxation",
        TaskType.BANDS: "Run band structure calculation on converged charge",
        TaskType.DOS: "Run density of states calculation on converged charge",
        TaskType.ELASTIC: "Run elastic properties workflow",
    }
    return mapping[task_type]


def _default_params(task_type: TaskType) -> Dict[str, str]:
    if task_type == TaskType.BANDS:
        return {"kline_mode": "high_symmetry"}
    if task_type == TaskType.DOS:
        return {"dos_mode": "total"}
    if task_type == TaskType.ELASTIC:
        return {"strain_set": "small_deformation"}
    return {}
