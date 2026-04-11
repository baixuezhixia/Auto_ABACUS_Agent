from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from result_parser import parse_abacus_result
from schema import CalcTask, ExecutionResult

WSL_PREFIX = "\\\\wsl.localhost\\Ubuntu-20.04\\"


def run_abacus_task(
    task: CalcTask,
    task_dir: Path,
    executable: str,
    run_mode: str,
    np: int,
    use_hwthread_cpus: bool = False,
    oversubscribe: bool = False,
) -> ExecutionResult:
    if run_mode not in {"mpirun", "local"}:
        raise ValueError(f"Unsupported run_mode: {run_mode}")

    cmd, cwd = _build_cmd(
        task_dir=task_dir,
        executable=executable,
        run_mode=run_mode,
        np=np,
        use_hwthread_cpus=use_hwthread_cpus,
        oversubscribe=oversubscribe,
    )
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=False,
        check=False,
    )

    stdout_text = _decode_output(proc.stdout)
    stderr_text = _decode_output(proc.stderr)
    stdout_tail = _tail(stdout_text, 2000)
    stderr_tail = _tail(stderr_text, 2000)
    status = "success" if proc.returncode == 0 else "failed"

    artifacts: Dict[str, str] = {}
    out_dir = task_dir / f"OUT.{task.task_id}"
    if out_dir.exists():
        artifacts["out_dir"] = str(out_dir)

    metrics = parse_abacus_result(task.task_type, task_dir, task.task_id)

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


def _build_cmd(
    task_dir: Path,
    executable: str,
    run_mode: str,
    np: int,
    use_hwthread_cpus: bool,
    oversubscribe: bool,
) -> Tuple[List[str], Optional[str]]:
    mpi_cmd = _mpi_cmd(executable, np, use_hwthread_cpus, oversubscribe)
    if _should_run_in_wsl(task_dir, executable):
        linux_cwd = _to_wsl_path(task_dir)
        inner = shlex.join(mpi_cmd if run_mode == "mpirun" else [executable])
        return ["wsl", "bash", "-lc", f"cd {shlex.quote(linux_cwd)} && {inner}"], None

    if run_mode == "local":
        return [executable], str(task_dir)
    return mpi_cmd, str(task_dir)


def _mpi_cmd(executable: str, np: int, use_hwthread_cpus: bool, oversubscribe: bool) -> List[str]:
    cmd = ["mpirun", "--allow-run-as-root"]
    if use_hwthread_cpus:
        cmd.append("--use-hwthread-cpus")
    if oversubscribe:
        cmd.append("--oversubscribe")
    cmd.extend(["-np", str(np), executable])
    return cmd


def _should_run_in_wsl(task_dir: Path, executable: str) -> bool:
    task_dir_str = str(task_dir)
    return task_dir_str.startswith(WSL_PREFIX) or executable.startswith("/")


def _to_wsl_path(path: Path) -> str:
    path_str = str(path)
    if not path_str.startswith(WSL_PREFIX):
        return path_str.replace("\\", "/")
    suffix = path_str[len(WSL_PREFIX):]
    return "/" + suffix.replace("\\", "/")


def _decode_output(data: Optional[bytes]) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
