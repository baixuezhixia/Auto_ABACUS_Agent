"""ABACUS command construction and task execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import platform
import re
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from autodft.core.enums import ArtifactType, TaskStatus
from autodft.core.exceptions import ExecutionError
from autodft.core.models import ArtifactRef, TaskExecutionRecord, TaskNode


WSL_PREFIX = "\\\\wsl.localhost\\Ubuntu-20.04\\"
RunCallable = Callable[..., subprocess.CompletedProcess]


@dataclass
class AbacusRunConfig:
    """Runtime command options for launching ABACUS."""

    executable: str = "abacus"
    run_mode: str = "mpirun"
    np: int = 8
    use_hwthread_cpus: bool = False
    oversubscribe: bool = False


def run_abacus_task(
    task: TaskNode,
    task_dir: str | Path,
    config: AbacusRunConfig,
    *,
    run_func: RunCallable = subprocess.run,
) -> TaskExecutionRecord:
    """Run ABACUS for one task and return a shared execution record."""

    if config.run_mode not in {"mpirun", "local"}:
        raise ExecutionError(f"Unsupported run_mode: {config.run_mode}")

    task_dir = Path(task_dir)
    cmd, cwd = build_command(
        task_dir=task_dir,
        executable=config.executable,
        run_mode=config.run_mode,
        np=config.np,
        use_hwthread_cpus=config.use_hwthread_cpus,
        oversubscribe=config.oversubscribe,
    )
    started_at = datetime.now().isoformat(timespec="seconds")
    proc = run_func(cmd, cwd=cwd, capture_output=True, text=False, check=False)
    finished_at = datetime.now().isoformat(timespec="seconds")

    stdout_text = _decode_output(proc.stdout)
    stderr_text = _decode_output(proc.stderr)
    status = TaskStatus.SUCCESS if proc.returncode == 0 else TaskStatus.FAILED
    out_dir = task_dir / f"OUT.{task.task_id}"
    log_sections, artifacts, error_summary = collect_abacus_logs(out_dir)
    for artifact in artifacts:
        artifact.task_id = task.task_id

    run_log = task_dir / "run.log"
    write_task_run_log(
        log_path=run_log,
        task=task,
        cmd=cmd,
        cwd=cwd,
        return_code=proc.returncode,
        status=status,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        abacus_sections=log_sections,
        abacus_error_summary=error_summary,
    )
    artifacts.insert(0, ArtifactRef(ArtifactType.RUN_LOG, str(run_log), task_id=task.task_id))
    if out_dir.exists():
        artifacts.append(ArtifactRef(ArtifactType.OUT_DIR, str(out_dir), task_id=task.task_id))

    metrics: Dict[str, str] = {}
    if error_summary:
        metrics["abacus_error_summary"] = error_summary

    return TaskExecutionRecord(
        task_id=task.task_id,
        task_type=task.task_type,
        status=status,
        work_dir=str(task_dir),
        return_code=proc.returncode,
        artifacts=artifacts,
        metrics=metrics,
        stdout_tail=_tail(stdout_text, 2000),
        stderr_tail=_tail(stderr_text, 2000),
        started_at=started_at,
        finished_at=finished_at,
    )


def build_command(
    *,
    task_dir: Path,
    executable: str,
    run_mode: str,
    np: int,
    use_hwthread_cpus: bool,
    oversubscribe: bool,
) -> Tuple[List[str], Optional[str]]:
    """Build the command and cwd for local, mpirun, or WSL execution."""

    mpi_cmd = mpi_command(executable, np, use_hwthread_cpus, oversubscribe)
    if should_run_in_wsl(task_dir, executable):
        linux_cwd = to_wsl_path(task_dir)
        inner = shlex.join(mpi_cmd if run_mode == "mpirun" else [executable])
        return ["wsl", "bash", "-lc", f"cd {shlex.quote(linux_cwd)} && {inner}"], None

    if run_mode == "local":
        return [executable], str(task_dir)
    return mpi_cmd, str(task_dir)


def mpi_command(executable: str, np: int, use_hwthread_cpus: bool, oversubscribe: bool) -> List[str]:
    """Build the mpirun command used by the current prototype."""

    cmd = ["mpirun", "--allow-run-as-root"]
    if use_hwthread_cpus:
        cmd.append("--use-hwthread-cpus")
    if oversubscribe:
        cmd.append("--oversubscribe")
    cmd.extend(["-np", str(np), executable])
    return cmd


def should_run_in_wsl(task_dir: Path, executable: str) -> bool:
    """Return whether Windows should dispatch this task through ``wsl``."""

    if platform.system().lower() != "windows":
        return False
    task_dir_str = str(task_dir)
    return task_dir_str.startswith(WSL_PREFIX) or executable.startswith("/")


def to_wsl_path(path: Path) -> str:
    """Convert a Windows WSL UNC path to a Linux path."""

    path_str = str(path)
    if not path_str.startswith(WSL_PREFIX):
        return path_str.replace("\\", "/")
    suffix = path_str[len(WSL_PREFIX):]
    return "/" + suffix.replace("\\", "/")


def collect_abacus_logs(out_dir: Path) -> Tuple[List[Tuple[str, str]], List[ArtifactRef], str]:
    """Collect ABACUS warning/running logs and a compact error summary."""

    if not out_dir.is_dir():
        return [], [], ""

    sections: List[Tuple[str, str]] = []
    artifacts: List[ArtifactRef] = []
    error_source = ""

    warning_log = out_dir / "warning.log"
    if warning_log.is_file():
        warning_text = _read_text(warning_log)
        sections.append(("ABACUS warning.log", warning_text))
        artifacts.append(ArtifactRef(ArtifactType.WARNING_LOG, str(warning_log)))
        error_source += warning_text + "\n"

    running_logs = sorted(path for path in out_dir.iterdir() if path.is_file() and path.name.startswith("running_") and path.suffix == ".log")
    for running_log in running_logs:
        running_text = _read_text(running_log)
        sections.append((f"ABACUS {running_log.name}", _tail(running_text, 20000)))
        artifacts.append(ArtifactRef(ArtifactType.OTHER, str(running_log), label="abacus_running_log"))
        error_source += running_text + "\n"

    return sections, artifacts, extract_abacus_error_summary(error_source)


def extract_abacus_error_summary(text: str) -> str:
    """Extract warning/error-like ABACUS log lines."""

    if not text:
        return ""
    pattern = re.compile(
        r"(error|warning|failed|incorrect|bad parameter|check in file|not found|cannot|no such|notice|unconverged|not converge)",
        re.IGNORECASE,
    )
    lines = [line.strip() for line in text.splitlines() if pattern.search(line)]
    unique_lines: List[str] = []
    seen = set()
    for line in lines:
        if line and line not in seen:
            unique_lines.append(line)
            seen.add(line)
        if len(unique_lines) >= 20:
            break
    return "\n".join(unique_lines)


def write_task_run_log(
    *,
    log_path: Path,
    task: TaskNode,
    cmd: List[str],
    cwd: Optional[str],
    return_code: int,
    status: TaskStatus,
    stdout_text: str,
    stderr_text: str,
    abacus_sections: List[Tuple[str, str]],
    abacus_error_summary: str,
) -> None:
    """Write a task run log in the current prototype's style."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        "=" * 80,
        f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
        f"task_id: {task.task_id}",
        f"task_type: {task.task_type.value}",
        f"status: {status.value}",
        f"return_code: {return_code}",
        f"cwd: {cwd or Path.cwd()}",
        f"command: {shlex.join(cmd)}",
        "",
        "--- ABACUS error summary ---",
        abacus_error_summary or "No ABACUS warning/error lines detected in OUT logs.",
        "",
        "--- stdout ---",
        stdout_text.rstrip(),
        "",
        "--- stderr ---",
        stderr_text.rstrip(),
        "",
    ]
    for title, content in abacus_sections:
        lines.extend([f"--- {title} ---", content.rstrip(), ""])
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


__all__ = [
    "AbacusRunConfig",
    "build_command",
    "collect_abacus_logs",
    "extract_abacus_error_summary",
    "mpi_command",
    "run_abacus_task",
    "should_run_in_wsl",
    "to_wsl_path",
    "write_task_run_log",
]
