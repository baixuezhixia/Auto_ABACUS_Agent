# 报告生成器，把整个 pipeline 的输入输出整理成一个 JSON 文件，
# 方便后续分析和展示

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from schema import CalcTask, ExecutionResult


def write_report(
    query: str,
    tasks: List[CalcTask],
    results: List[ExecutionResult],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "query": query,
        "tasks": [
            {
                "task_id": t.task_id,
                "task_type": t.task_type.value,
                "description": t.description,
                "depends_on": t.depends_on,
                "params": t.params,
            }
            for t in tasks
        ],
        "execution": [
            {
                "task_id": r.task_id,
                "task_type": r.task_type,
                "status": r.status,
                "return_code": r.return_code,
                "work_dir": r.work_dir,
                "artifacts": r.artifacts,
                "metrics": r.metrics,
                "stdout_tail": r.stdout_tail,
                "stderr_tail": r.stderr_tail,
            }
            for r in results
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path
