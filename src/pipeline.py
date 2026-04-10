# 整个 pipeline 的核心逻辑，在这里把前面几个模块串起来，形成一个完整的流程
# 从输入的 query 和结构文件开始，经过任务解码、输入构建、任务执行、结果解析，最后生成一个报告

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

from abacus_runner import run_abacus_task
from input_builder import build_task_inputs
from llm_decoder import decode_tasks_with_llm
from report import write_report
from schema import CalcTask, ExecutionResult, PipelineResult, TaskType
from task_decoder import decode_tasks


def run_pipeline(
    query: str,
    structure_path: str,
    work_dir: str,
    cfg: Dict,
    task_plan: Optional[Sequence[str]] = None,
) -> PipelineResult:
    decoder_cfg = cfg.get("decoder", {})
    tasks = _resolve_tasks(query, task_plan, decoder_cfg)
    run_root = Path(work_dir).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    structure = Path(structure_path).resolve()

    defaults = cfg.get("defaults", {}).get("calculation", {})
    abacus_cfg = cfg.get("abacus", {})
    executable = abacus_cfg.get("executable", "abacus")
    run_mode = abacus_cfg.get("run_mode", "mpirun")
    np = int(abacus_cfg.get("np", 8))
    pseudo_dir = abacus_cfg.get("pseudo_dir", "")
    orb_dir = abacus_cfg.get("orb_dir", abacus_cfg.get("orbital_dir", ""))

    execution_results: List[ExecutionResult] = []
    task_dirs_by_id: Dict[str, Path] = {}
    for idx, task in enumerate(tasks, start=1):
        task_dir = run_root / f"{idx:02d}_{task.task_type.value}"
        dependency_task_id = task.depends_on[-1] if task.depends_on else None
        dependency_task_dir = task_dirs_by_id.get(dependency_task_id) if dependency_task_id else None
        build_task_inputs(
            task=task,
            task_dir=task_dir,
            structure_path=structure,
            default_cfg=defaults,
            pseudo_dir=pseudo_dir,
            orb_dir=orb_dir,
            dependency_task_dir=dependency_task_dir,
            dependency_task_id=dependency_task_id,
        )
        result = run_abacus_task(
            task=task,
            task_dir=task_dir,
            executable=executable,
            run_mode=run_mode,
            np=np,
        )
        execution_results.append(result)
        task_dirs_by_id[task.task_id] = task_dir

    success_count = sum(1 for r in execution_results if r.status == "success")
    summary = f"Executed {len(execution_results)} tasks, success {success_count}, failed {len(execution_results) - success_count}."

    report_path = write_report(
        query=query,
        tasks=tasks,
        results=execution_results,
        output_path=run_root / "report.json",
    )

    return PipelineResult(
        query=query,
        tasks=tasks,
        execution=execution_results,
        summary=summary,
        report_path=str(report_path),
    )


def _resolve_tasks(query: str, task_plan: Optional[Sequence[str]], decoder_cfg: Dict) -> List[CalcTask]:
    if task_plan:
        resolved: List[CalcTask] = []
        prev = ""
        for idx, name in enumerate(task_plan, start=1):
            task_type = TaskType(name.strip().lower())
            task_id = f"t{idx}_{task_type.value}"
            deps = [prev] if prev else []
            resolved.append(
                CalcTask(
                    task_id=task_id,
                    task_type=task_type,
                    description=f"Run {task_type.value}",
                    depends_on=deps,
                    params={},
                )
            )
            prev = task_id
        return resolved

    decoder_mode = str(decoder_cfg.get("mode", "rule")).lower()
    if decoder_mode in {"llm", "auto"}:
        try:
            return decode_tasks_with_llm(query, decoder_cfg)
        except Exception:
            if decoder_mode == "llm":
                raise
    return decode_tasks(query)
