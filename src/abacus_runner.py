# ABACUS 任务执行器，负责在指定目录下运行 ABACUS，并收集结果

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

from schema import CalcTask, ExecutionResult
from result_parser import parse_abacus_result


def run_abacus_task(
    task: CalcTask,
    task_dir: Path,
    executable: str,
    run_mode: str,
    np: int,
) -> ExecutionResult:
    if run_mode not in {"mpirun", "local"}:
        raise ValueError(f"Unsupported run_mode: {run_mode}")

    cmd = _build_cmd(executable=executable, run_mode=run_mode, np=np)
    proc = subprocess.run(
        cmd,
        cwd=str(task_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    stdout_tail = _tail(proc.stdout, 2000)
    stderr_tail = _tail(proc.stderr, 2000)
    status = "success" if proc.returncode == 0 else "failed"

    artifacts: Dict[str, str] = {}
    out_dir = task_dir / "OUT.ABACUS"
    if out_dir.exists():
        artifacts["out_dir"] = str(out_dir)

    metrics = parse_abacus_result(task.task_type, task_dir)

    return ExecutionResult(
        task_id=task.task_id,
        task_type=task.task_type.value,
        work_dir=str(task_dir),
        return_code=proc.returncode,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        status=status,
        artifacts=artifacts,
        metrics=metrics,
    )


def _build_cmd(executable: str, run_mode: str, np: int):
    if run_mode == "local":
        return [executable]
    return ["mpirun", "--allow-run-as-root", "-np", str(np), executable]


def _tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
