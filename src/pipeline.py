from __future__ import annotations

from datetime import datetime
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
    run_log = run_root / "run.log"
    _write_run_log(run_log, f"Started pipeline for query: {query}")
    _write_run_log(run_log, f"Work directory: {run_root}")

    structure_artifact, notices = fetch_conventional_cif(
        structure_input=structure_input,
        work_dir=work_dir,
        query=query,
        selection_cfg=cfg.get("mp_selection", {}),
    )
    notices = list(notices)
    _write_run_log(run_log, f"Selected structure: {structure_artifact.material_id} ({structure_artifact.formula})")

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
    _write_run_log(run_log, f"Generated ABACUS STRU: {generated_stru}")

    execution_results: List[ExecutionResult] = []
    task_dirs_by_id: Dict[str, Path] = {}
    structure_paths_by_id: Dict[str, Path] = {}
    for idx, task in enumerate(tasks, start=1):
        task_dir = run_root / f"{idx:02d}_{task.task_type.value}"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_log = task_dir / "run.log"
        _write_run_log(run_log, f"Starting {task.task_id} ({task.task_type.value}) in {task_dir}")
        _write_run_log(task_log, f"Preparing {task.task_id} ({task.task_type.value})")
        _write_run_log(task_log, f"Depends on: {task.depends_on or 'none'}")

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
        _write_run_log(task_log, f"Using structure: {structure_path}")
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
        _write_run_log(task_log, "Generated INPUT, STRU, and KPT files")
        result = run_abacus_task(
            task=task,
            task_dir=task_dir,
            executable=executable,
            run_mode=run_mode,
            np=np,
            use_hwthread_cpus=use_hwthread_cpus,
            oversubscribe=oversubscribe,
        )
        _write_run_log(run_log, f"Finished {task.task_id} with status={result.status}, return_code={result.return_code}")
        if result.status != "success":
            _write_run_log(run_log, f"FAILED TASK: {task.task_id} ({task.task_type.value})")
            _write_run_log(run_log, f"Task log: {result.artifacts.get('run_log', task_log)}")
            abacus_summary = result.artifacts.get("abacus_error_summary")
            if abacus_summary:
                _write_run_log(run_log, "ABACUS error summary:")
                for line in abacus_summary.splitlines():
                    _write_run_log(run_log, f"  {line}")
        execution_results.append(result)
        task_dirs_by_id[task.task_id] = task_dir
        structure_paths_by_id[task.task_id] = task_dir / "STRU"

    success_count = sum(1 for r in execution_results if r.status == "success")
    summary = f"Executed {len(execution_results)} tasks, success {success_count}, failed {len(execution_results) - success_count}."
    _write_run_log(run_log, summary)

    report_path = write_report(
        query=query,
        tasks=tasks,
        results=execution_results,
        output_path=run_root / "report.json",
        structure_artifact=structure_artifact,
        notices=notices,
    )
    _write_run_log(run_log, f"Wrote report: {report_path}")

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
    basis_type = _detect_basis_type(query)
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
                    params=_params_with_basis({}, basis_type),
                )
            )
        return _normalize_workflow(resolved, query=query)

    decoder_mode = str(decoder_cfg.get("mode", "rule")).lower()
    if decoder_mode in {"llm", "auto"}:
        try:
            return _normalize_workflow(decode_tasks_with_llm(query, decoder_cfg), query=query)
        except Exception:
            if decoder_mode == "llm":
                raise
    return _normalize_workflow(decode_tasks(query), query=query)


def _normalize_workflow(tasks: Sequence[CalcTask], *, query: str = "") -> List[CalcTask]:
    """Complete dependencies while preserving the user's task order."""
    ordered_sources: List[CalcTask] = []
    seen: set[TaskType] = set()
    for task in tasks:
        if task.task_type not in seen:
            seen.add(task.task_type)
            ordered_sources.append(task)
    basis_type = _first_basis_type(tasks)

    if not ordered_sources:
        ordered_sources.append(_legacy_task(TaskType.SCF, basis_type, query))

    present = {task.task_type for task in ordered_sources}
    if TaskType.ELASTIC in present and TaskType.RELAX not in present:
        _insert_legacy_before_first(ordered_sources, _legacy_task(TaskType.RELAX, basis_type, query), {TaskType.ELASTIC})
        present.add(TaskType.RELAX)

    needs_scf = any(task.task_type in {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC} for task in ordered_sources)
    if needs_scf and TaskType.SCF not in present:
        _insert_legacy_before_first(
            ordered_sources,
            _legacy_task(TaskType.SCF, basis_type, query),
            {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC},
        )

    normalized: List[CalcTask] = []
    ids_by_type: Dict[TaskType, str] = {}

    for source in ordered_sources:
        task_type = source.task_type

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
                params=_params_with_basis_and_relax_mode(source.params, basis_type, task_type, query),
            )
        )
        ids_by_type[task_type] = task_id

    return normalized


def _legacy_task(task_type: TaskType, basis_type: Optional[str], query: str) -> CalcTask:
    return CalcTask(
        task_id="",
        task_type=task_type,
        description="Run self-consistent electronic structure calculation" if task_type == TaskType.SCF else f"Run {task_type.value}",
        depends_on=[],
        params=_params_with_basis_and_relax_mode({}, basis_type, task_type, query),
    )


def _insert_legacy_before_first(tasks: List[CalcTask], inserted: CalcTask, target_types: set[TaskType]) -> None:
    for index, task in enumerate(tasks):
        if task.task_type in target_types:
            tasks.insert(index, inserted)
            return
    tasks.append(inserted)


def _first_basis_type(tasks: Sequence[CalcTask]) -> Optional[str]:
    for task in tasks:
        basis_type = task.params.get("basis_type")
        if basis_type:
            return str(basis_type)
    return None


def _params_with_basis(params: Dict, basis_type: Optional[str]) -> Dict:
    merged = dict(params)
    if basis_type is not None:
        merged.setdefault("basis_type", basis_type)
    return merged


def _params_with_basis_and_relax_mode(params: Dict, basis_type: Optional[str], task_type: TaskType, query: str) -> Dict:
    merged = _params_with_basis(params, basis_type)
    if task_type == TaskType.RELAX and _detect_full_relax(query):
        merged.setdefault("calculation", "cell-relax")
    return merged


def _detect_full_relax(text: str) -> bool:
    import re

    return re.search(r"\bfully\s+relax\b", text, re.IGNORECASE) is not None


def _detect_basis_type(text: str) -> Optional[str]:
    lowered = text.lower()
    if _contains_token(lowered, "lcao"):
        return "lcao"
    if _contains_token(lowered, "pw"):
        return "pw"
    return None


def _contains_token(text: str, token: str) -> bool:
    import re

    token_boundary = r"[A-Za-z0-9_]"
    pattern = rf"(?<!{token_boundary}){re.escape(token)}(?!{token_boundary})"
    return re.search(pattern, text, re.IGNORECASE) is not None


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


def _write_run_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")
