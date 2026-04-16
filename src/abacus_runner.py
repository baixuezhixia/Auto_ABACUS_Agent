from __future__ import annotations

from datetime import datetime
import platform
import re
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
    out_dir = task_dir / f"OUT.{task.task_id}"
    abacus_sections, abacus_artifacts, abacus_error_summary = _collect_abacus_logs(out_dir)

    run_log = task_dir / "run.log"
    _write_task_run_log(
        log_path=run_log,
        task=task,
        cmd=cmd,
        cwd=cwd,
        return_code=proc.returncode,
        status=status,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        abacus_sections=abacus_sections,
        abacus_error_summary=abacus_error_summary,
    )

    artifacts: Dict[str, str] = {}
    artifacts["run_log"] = str(run_log)
    artifacts.update(abacus_artifacts)
    if abacus_error_summary:
        artifacts["abacus_error_summary"] = abacus_error_summary
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
    # Only Windows hosts should launch Linux commands via `wsl`.
    if platform.system().lower() != "windows":
        return False
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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _collect_abacus_logs(out_dir: Path) -> Tuple[List[Tuple[str, str]], Dict[str, str], str]:
    if not out_dir.is_dir():
        return [], {}, ""

    sections: List[Tuple[str, str]] = []
    artifacts: Dict[str, str] = {}
    error_source = ""

    warning_log = out_dir / "warning.log"
    if warning_log.is_file():
        warning_text = _read_text(warning_log)
        sections.append(("ABACUS warning.log", warning_text))
        artifacts["abacus_warning_log"] = str(warning_log)
        error_source += warning_text + "\n"

    running_logs = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name.startswith("running_") and path.suffix == ".log"
    )
    for index, running_log in enumerate(running_logs, start=1):
        running_text = _read_text(running_log)
        sections.append((f"ABACUS {running_log.name}", _tail(running_text, 20000)))
        artifacts[f"abacus_running_log_{index}"] = str(running_log)
        error_source += running_text + "\n"

    return sections, artifacts, _extract_abacus_error_summary(error_source)


def _extract_abacus_error_summary(text: str) -> str:
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


def _write_task_run_log(
    log_path: Path,
    task: CalcTask,
    cmd: List[str],
    cwd: Optional[str],
    return_code: int,
    status: str,
    stdout_text: str,
    stderr_text: str,
    abacus_sections: List[Tuple[str, str]],
    abacus_error_summary: str,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        "=" * 80,
        f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
        f"task_id: {task.task_id}",
        f"task_type: {task.task_type.value}",
        f"status: {status}",
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
