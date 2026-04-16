from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from schema import CalcTask, ExecutionResult, StructureArtifact


def write_report(
    query: str,
    tasks: List[CalcTask],
    results: List[ExecutionResult],
    output_path: Path,
    structure_artifact: Optional[StructureArtifact] = None,
    notices: Optional[List[str]] = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "query": query,
        "structure": None,
        "notices": notices or [],
        "run_log": str(output_path.parent / "run.log"),
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
    if structure_artifact is not None:
        payload["structure"] = {
            "source": structure_artifact.source,
            "input": structure_artifact.input,
            "material_id": structure_artifact.material_id,
            "formula": structure_artifact.formula,
            "cif_path": structure_artifact.cif_path,
            "lattice_type": structure_artifact.lattice_type,
            "candidates": structure_artifact.candidates,
        }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path
