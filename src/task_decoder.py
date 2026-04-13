from __future__ import annotations

import re
from typing import Dict, List

from schema import CalcTask, TaskType


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
        r"\bband(?:\s*structure)?\b",
        r"\u80fd\u5e26",
    ],
    TaskType.DOS: [
        r"\bdos\b",
        r"density\s+of\s+states",
        r"\u6001\u5bc6\u5ea6",
    ],
    TaskType.ELASTIC: [
        r"elastic",
        r"\u5f39\u6027",
        r"elastic\s+properties",
    ],
}


_TOKEN_BOUNDARY = r"[A-Za-z0-9_]"


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
    basis_type = _detect_basis_type(text)

    for ttype, plist in _PATTERNS.items():
        if _contains_any(text, plist):
            detected.append(ttype)

    if TaskType.BANDS in detected and TaskType.SCF not in detected:
        detected.insert(0, TaskType.SCF)
    if TaskType.DOS in detected and TaskType.SCF not in detected:
        detected.insert(0, TaskType.SCF)

    if TaskType.ELASTIC in detected:
        if TaskType.RELAX not in detected:
            detected.insert(0, TaskType.RELAX)
        if TaskType.SCF not in detected:
            detected.insert(1, TaskType.SCF)

    detected = _ordered_unique(detected)

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
                params=_default_params(ttype, basis_type),
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



def _default_params(task_type: TaskType, basis_type: str | None = None) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if basis_type:
        params["basis_type"] = basis_type
    if task_type == TaskType.BANDS:
        params["kline_mode"] = "high_symmetry"
    if task_type == TaskType.DOS:
        params["dos_mode"] = "total"
    if task_type == TaskType.ELASTIC:
        params["strain_set"] = "small_deformation"
    return params



def _contains_token(text: str, token: str) -> bool:
    pattern = rf"(?<!{_TOKEN_BOUNDARY}){re.escape(token)}(?!{_TOKEN_BOUNDARY})"
    return re.search(pattern, text, re.IGNORECASE) is not None



def _detect_basis_type(text: str) -> str | None:
    lowered = text.lower()
    if _contains_token(lowered, "lcao"):
        return "lcao"
    if _contains_token(lowered, "pw"):
        return "pw"
    return None
