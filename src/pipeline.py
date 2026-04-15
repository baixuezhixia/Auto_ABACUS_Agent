from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

from abacus_runner import run_abacus_task
from cif_to_stru import convert_cif_to_stru
from llm_decoder import decode_tasks_with_llm
from mp_structure_fetcher import fetch_conventional_cif
from input_builder import build_task_inputs
from report import write_report
from schema import CalcTask, ExecutionResult, PipelineResult, TaskType
from task_decoder import decode_tasks


def run_pipeline(
    query: str,
    structure_input: str,
    work_dir: str,
    cfg: Dict,
    task_plan: Optional[Sequence[str]] = None,
) -> PipelineResult:
    decoder_cfg = cfg.get("decoder", {})
    tasks = _resolve_tasks(query, task_plan, decoder_cfg)
    run_root = Path(work_dir).resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    structure_artifact, notices = fetch_conventional_cif(
        structure_input=structure_input,
        work_dir=work_dir,
        query=query,
        selection_cfg=cfg.get("mp_selection", {}),
    )
    notices = list(notices)

    defaults = cfg.get("defaults", {}).get("calculation", {})
    abacus_cfg = cfg.get("abacus", {})
    executable = abacus_cfg.get("executable", "abacus")
    run_mode = abacus_cfg.get("run_mode", "mpirun")
    np = int(abacus_cfg.get("np", 8))
    pseudo_dir = abacus_cfg.get("pseudo_dir", "")
    orb_dir = abacus_cfg.get("orb_dir", abacus_cfg.get("orbital_dir", ""))
    use_hwthread_cpus = bool(abacus_cfg.get("use_hwthread_cpus", False))
    oversubscribe = bool(abacus_cfg.get("oversubscribe", False))

    generated_stru = run_root / "materials_project" / f"{structure_artifact.material_id}.STRU"
    convert_cif_to_stru(
        cif_path=structure_artifact.cif_path,
        output_path=str(generated_stru),
        pseudo_dir=pseudo_dir,
        orb_dir=orb_dir,
        include_numerical_orbital=False,
    )
    notices.append(f"Generated ABACUS STRU from CIF: {generated_stru}")

    execution_results: List[ExecutionResult] = []
    task_dirs_by_id: Dict[str, Path] = {}
    structure_paths_by_id: Dict[str, Path] = {}
    for idx, task in enumerate(tasks, start=1):
        task_dir = run_root / f"{idx:02d}_{task.task_type.value}"
        dependency_task_id = task.depends_on[-1] if task.depends_on else None
        dependency_task_dir = task_dirs_by_id.get(dependency_task_id) if dependency_task_id else None
        structure_path = _resolve_structure_path_for_task(
            task=task,
            generated_stru=generated_stru,
            dependency_task_id=dependency_task_id,
            dependency_task_dir=dependency_task_dir,
            structure_paths_by_id=structure_paths_by_id,
            run_root=run_root,
            pseudo_dir=pseudo_dir,
            orb_dir=orb_dir,
            notices=notices,
        )
        build_task_inputs(
            task=task,
            task_dir=task_dir,
            structure_path=structure_path,
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
            use_hwthread_cpus=use_hwthread_cpus,
            oversubscribe=oversubscribe,
        )
        execution_results.append(result)
        task_dirs_by_id[task.task_id] = task_dir
        structure_paths_by_id[task.task_id] = task_dir / "STRU"

    success_count = sum(1 for r in execution_results if r.status == "success")
    summary = f"Executed {len(execution_results)} tasks, success {success_count}, failed {len(execution_results) - success_count}."

    report_path = write_report(
        query=query,
        tasks=tasks,
        results=execution_results,
        output_path=run_root / "report.json",
        structure_artifact=structure_artifact,
        notices=notices,
    )

    return PipelineResult(
        query=query,
        tasks=tasks,
        execution=execution_results,
        summary=summary,
        report_path=str(report_path),
        structure_artifact=structure_artifact,
        notices=notices,
    )


def _resolve_tasks(query: str, task_plan: Optional[Sequence[str]], decoder_cfg: Dict) -> List[CalcTask]:
    if task_plan:
        resolved: List[CalcTask] = []
        for idx, name in enumerate(task_plan, start=1):
            task_type = TaskType(name.strip().lower())
            task_id = f"t{idx}_{task_type.value}"
            resolved.append(
                CalcTask(
                    task_id=task_id,
                    task_type=task_type,
                    description=f"Run {task_type.value}",
                    depends_on=[],
                    params={},
                )
            )
        return _normalize_workflow(resolved)

    decoder_mode = str(decoder_cfg.get("mode", "rule")).lower()
    if decoder_mode in {"llm", "auto"}:
        try:
            return _normalize_workflow(decode_tasks_with_llm(query, decoder_cfg))
        except Exception:
            if decoder_mode == "llm":
                raise
    return _normalize_workflow(decode_tasks(query))


def _normalize_workflow(tasks: Sequence[CalcTask]) -> List[CalcTask]:
    """Use the physically meaningful ABACUS flow: relax -> scf -> bands/dos."""
    by_type: Dict[TaskType, CalcTask] = {}
    for task in tasks:
        by_type.setdefault(task.task_type, task)

    if (TaskType.BANDS in by_type or TaskType.DOS in by_type or TaskType.ELASTIC in by_type) and TaskType.SCF not in by_type:
        by_type[TaskType.SCF] = CalcTask(
            task_id="",
            task_type=TaskType.SCF,
            description="Run self-consistent electronic structure calculation",
            depends_on=[],
            params={},
        )

    ordered_types = [
        TaskType.RELAX,
        TaskType.SCF,
        TaskType.BANDS,
        TaskType.DOS,
        TaskType.ELASTIC,
    ]
    normalized: List[CalcTask] = []
    ids_by_type: Dict[TaskType, str] = {}

    for task_type in ordered_types:
        source = by_type.get(task_type)
        if source is None:
            continue

        task_id = f"t{len(normalized) + 1}_{task_type.value}"
        depends_on: List[str] = []
        if task_type == TaskType.SCF and TaskType.RELAX in ids_by_type:
            depends_on = [ids_by_type[TaskType.RELAX]]
        elif task_type in {TaskType.BANDS, TaskType.DOS} and TaskType.SCF in ids_by_type:
            depends_on = [ids_by_type[TaskType.SCF]]
        elif task_type == TaskType.ELASTIC:
            if TaskType.SCF in ids_by_type:
                depends_on = [ids_by_type[TaskType.SCF]]
            elif TaskType.RELAX in ids_by_type:
                depends_on = [ids_by_type[TaskType.RELAX]]

        normalized.append(
            CalcTask(
                task_id=task_id,
                task_type=task_type,
                description=source.description or f"Run {task_type.value}",
                depends_on=depends_on,
                params=dict(source.params),
            )
        )
        ids_by_type[task_type] = task_id

    return normalized


def _resolve_structure_path_for_task(
    task: CalcTask,
    generated_stru: Path,
    dependency_task_id: Optional[str],
    dependency_task_dir: Optional[Path],
    structure_paths_by_id: Dict[str, Path],
    run_root: Path,
    pseudo_dir: str,
    orb_dir: str,
    notices: List[str],
) -> Path:
    if dependency_task_id is None or dependency_task_dir is None:
        return generated_stru

    dependency_structure = structure_paths_by_id.get(dependency_task_id)
    if task.task_type in {TaskType.BANDS, TaskType.DOS} and dependency_structure is not None:
        return dependency_structure

    relaxed_cif = dependency_task_dir / f"OUT.{dependency_task_id}" / "STRU.cif"
    if relaxed_cif.is_file():
        relaxed_stru = run_root / "relaxed_structures" / f"{dependency_task_id}.STRU"
        convert_cif_to_stru(
            cif_path=str(relaxed_cif),
            output_path=str(relaxed_stru),
            pseudo_dir=pseudo_dir,
            orb_dir=orb_dir,
            include_numerical_orbital=False,
        )
        notices.append(f"Using relaxed structure from {relaxed_cif} for {task.task_id}.")
        return relaxed_stru

    if dependency_structure is not None:
        return dependency_structure

    notices.append(
        f"No relaxed structure found for dependency {dependency_task_id}; using initial structure for {task.task_id}."
    )
    return generated_stru
