"""Phase-1 workflow executor built on the new architecture."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from autodft.abacus.input_generator import generate_abacus_inputs, has_charge_handoff_files
from autodft.abacus.structure_io import convert_cif_to_stru
from autodft.core.enums import ArtifactType, BasisType, TaskStatus, TaskType
from autodft.core.exceptions import StructureResolutionError
from autodft.core.models import ArtifactRef, RunSummary, TaskExecutionRecord, TaskNode, WorkflowSpec
from autodft.parsers import RunParser
from autodft.planners.rule_planner import RulePlanner
from autodft.reports import write_json_report, write_summary_report
from autodft.structures import StructureResolver
from autodft.structures.structure_object import artifact_path
from autodft.workflows.artifact_store import ArtifactStore
from autodft.workflows.dependency_graph import DependencyGraph
from autodft.workflows.spec import TaskRuntimePaths, WorkflowExecutionConfig


RunFunction = Callable[..., object]


class WorkflowExecutor:
    """Execute a normalized workflow one task at a time."""

    def __init__(
        self,
        config: WorkflowExecutionConfig,
        *,
        run_func: Optional[RunFunction] = None,
        run_parser: Optional[RunParser] = None,
    ) -> None:
        self.config = config
        self.run_func = run_func
        self.run_parser = run_parser or RunParser()
        self.artifacts = ArtifactStore()
        self.notices: List[str] = []

    def execute(self, workflow: WorkflowSpec) -> RunSummary:
        """Execute a workflow in dependency order and return a run summary."""

        root = self.config.root
        root.mkdir(parents=True, exist_ok=True)

        if workflow.structure is None:
            raise StructureResolutionError("WorkflowSpec.structure is required before execution.")
        self.artifacts.set_structure(workflow.structure)

        base_stru = self._prepare_base_structure(workflow)
        graph = DependencyGraph(workflow)
        executions: List[TaskExecutionRecord] = []

        for index, task in enumerate(graph.execution_order(), start=1):
            blocked_by = self._blocked_dependency(task)
            if blocked_by is not None:
                record = self._skip_blocked_task(task, root, index, blocked_by)
                executions.append(record)
                self.artifacts.add_execution(record)
                task.status = record.status
                continue

            runtime_paths = self._runtime_paths_for_task(index, task, root, base_stru)
            input_set = generate_abacus_inputs(
                task,
                runtime_paths.task_dir,
                runtime_paths.structure_path,
                preset=self.config.abacus_preset,
                resources=self.config.abacus_resources,
                dependency_task_dir=runtime_paths.dependency_task_dir,
                dependency_task_id=runtime_paths.dependency_task_id,
            )
            self._notice_scf_handoff(task, runtime_paths.task_dir, runtime_paths.dependency_task_id)
            self.artifacts.add_many(input_set.artifacts(task.task_id))
            record = self._run_task(task, runtime_paths.task_dir)
            self.run_parser.update_record(record)
            executions.append(record)
            self.artifacts.add_execution(record)
            self.artifacts.register_task_dir(task.task_id, runtime_paths.task_dir)
            self.artifacts.register_task_structure(task.task_id, input_set.stru_path)
            task.status = record.status

            if record.status == TaskStatus.FAILED and self.config.stop_on_failure:
                self.notices.append(f"Stopped after failed task {task.task_id}.")
                break

        status = TaskStatus.SUCCESS if executions and all(item.status == TaskStatus.SUCCESS for item in executions) else TaskStatus.FAILED
        if not executions:
            status = TaskStatus.SKIPPED
        summary = RunSummary(
            workflow=workflow,
            status=status,
            executions=executions,
            notices=list(self.notices),
            metadata={"artifact_count": len(self.artifacts.artifacts)},
        )
        report_path = root / "report.json"
        write_json_report(summary, report_path)
        summary_path = root / "summary.txt"
        write_summary_report(summary, summary_path)
        self.artifacts.add(ArtifactRef(ArtifactType.REPORT, str(report_path), label="report"))
        self.artifacts.add(ArtifactRef(ArtifactType.REPORT, str(summary_path), label="summary"))
        return summary

    def _prepare_base_structure(self, workflow: WorkflowSpec) -> Path:
        cif_path = artifact_path(workflow.structure, ArtifactType.CIF) if workflow.structure else None
        stru_path = artifact_path(workflow.structure, ArtifactType.STRU) if workflow.structure else None
        if stru_path:
            return Path(stru_path)
        if not cif_path:
            raise StructureResolutionError("Resolved structure must include a CIF or STRU artifact.")

        output_path = self.config.root / "materials_project" / f"{workflow.structure.structure_id}.STRU"
        convert_cif_to_stru(
            cif_path,
            output_path,
            self.config.abacus_resources,
            basis_type=BasisType.PW,
        )
        artifact = ArtifactRef(ArtifactType.STRU, str(output_path), label="base_stru")
        workflow.structure.artifacts.append(artifact)
        self.artifacts.add(artifact)
        self.notices.append(f"Generated ABACUS STRU from CIF: {output_path}")
        return output_path

    def _runtime_paths_for_task(self, index: int, task: TaskNode, root: Path, base_stru: Path) -> TaskRuntimePaths:
        task_dir = root / f"{index:02d}_{task.task_type.value}"
        task_dir.mkdir(parents=True, exist_ok=True)
        dependency_task_id = task.depends_on[-1] if task.depends_on else None
        dependency_task_dir = self.artifacts.task_dirs.get(dependency_task_id) if dependency_task_id else None
        structure_path = self._resolve_structure_for_task(
            task=task,
            base_stru=base_stru,
            dependency_task_id=dependency_task_id,
            dependency_task_dir=dependency_task_dir,
        )
        return TaskRuntimePaths(
            task_dir=task_dir,
            structure_path=structure_path,
            dependency_task_id=dependency_task_id,
            dependency_task_dir=dependency_task_dir,
        )

    def _resolve_structure_for_task(
        self,
        *,
        task: TaskNode,
        base_stru: Path,
        dependency_task_id: Optional[str],
        dependency_task_dir: Optional[Path],
    ) -> Path:
        if dependency_task_id is None or dependency_task_dir is None:
            return base_stru
        if not self._is_dependency_record_valid(dependency_task_id):
            self.notices.append(f"Dependency {dependency_task_id} is not valid for structure handoff; using initial structure for {task.task_id}.")
            return base_stru

        dependency_record = self.artifacts.execution_records.get(dependency_task_id)
        dependency_structure = self.artifacts.structure_paths.get(dependency_task_id)
        if task.task_type in {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC} and dependency_record is not None and dependency_record.task_type == TaskType.SCF and dependency_structure is not None:
            self.notices.append(f"Using SCF structure from {dependency_structure} for {task.task_id}.")
            return dependency_structure
        if task.task_type in {TaskType.BANDS, TaskType.DOS} and dependency_structure is not None:
            return dependency_structure

        relaxed_cif = self._relaxed_cif_path(dependency_task_id)
        if relaxed_cif.is_file():
            relaxed_stru = self.config.root / "relaxed_structures" / f"{dependency_task_id}.STRU"
            convert_cif_to_stru(
                relaxed_cif,
                relaxed_stru,
                self.config.abacus_resources,
                basis_type=BasisType.PW,
            )
            self.notices.append(f"Using relaxed structure from {relaxed_cif} for {task.task_id}.")
            self.artifacts.add(ArtifactRef(ArtifactType.STRU, str(relaxed_stru), task_id=dependency_task_id, label="relaxed_stru"))
            return relaxed_stru

        if dependency_record is not None and dependency_record.task_type == TaskType.RELAX and task.task_type == TaskType.SCF:
            self.notices.append(f"No relaxed structure found for dependency {dependency_task_id}; cannot prepare relaxed SCF input for {task.task_id}.")
            return base_stru

        if dependency_structure is not None:
            return dependency_structure

        self.notices.append(f"No relaxed structure found for dependency {dependency_task_id}; using initial structure for {task.task_id}.")
        return base_stru

    def _blocked_dependency(self, task: TaskNode) -> Optional[str]:
        for dependency_id in task.depends_on:
            if not self._is_dependency_record_valid(dependency_id):
                return dependency_id
            if self._requires_relaxed_structure(task, dependency_id) and not self._relaxed_cif_path(dependency_id).is_file():
                self.notices.append(f"Skipped {task.task_id} because dependency {dependency_id} did not produce OUT.{dependency_id}/STRU.cif.")
                return dependency_id
            if self._requires_scf_charge(task, dependency_id) and not has_charge_handoff_files(self._out_dir_for_task(dependency_id)):
                self.notices.append(f"Skipped {task.task_id} because dependency {dependency_id} did not produce reusable SCF charge-density files.")
                return dependency_id
        return None

    def _requires_relaxed_structure(self, task: TaskNode, dependency_id: str) -> bool:
        dependency_record = self.artifacts.execution_records.get(dependency_id)
        return task.task_type == TaskType.SCF and dependency_record is not None and dependency_record.task_type == TaskType.RELAX

    def _requires_scf_charge(self, task: TaskNode, dependency_id: str) -> bool:
        dependency_record = self.artifacts.execution_records.get(dependency_id)
        return task.task_type in {TaskType.BANDS, TaskType.DOS} and dependency_record is not None and dependency_record.task_type == TaskType.SCF

    def _relaxed_cif_path(self, dependency_task_id: str) -> Path:
        dependency_task_dir = self.artifacts.task_dirs.get(dependency_task_id)
        if dependency_task_dir is None:
            return self.config.root / f"missing_{dependency_task_id}" / "STRU.cif"
        return dependency_task_dir / f"OUT.{dependency_task_id}" / "STRU.cif"

    def _out_dir_for_task(self, task_id: str) -> Path:
        task_dir = self.artifacts.task_dirs.get(task_id)
        if task_dir is None:
            return self.config.root / f"missing_{task_id}"
        return task_dir / f"OUT.{task_id}"

    def _notice_scf_handoff(self, task: TaskNode, task_dir: Path, dependency_task_id: Optional[str]) -> None:
        if dependency_task_id is None or task.task_type not in {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC}:
            return
        dependency_record = self.artifacts.execution_records.get(dependency_task_id)
        if dependency_record is None or dependency_record.task_type != TaskType.SCF:
            return
        read_chg = task_dir / "READ_CHG"
        if read_chg.is_dir() and self._staged_charge_files_present(read_chg):
            self.notices.append(f"Using SCF charge artifacts from OUT.{dependency_task_id} for {task.task_id}.")

    def _staged_charge_files_present(self, read_chg: Path) -> bool:
        return any(read_chg.glob("*-CHARGE-DENSITY.restart")) or any((read_chg / name).is_file() for name in ("chg.cube", "chg1.cube", "chg2.cube"))

    def _is_dependency_record_valid(self, task_id: str) -> bool:
        record = self.artifacts.execution_records.get(task_id)
        if record is None:
            return False
        if record.status != TaskStatus.SUCCESS:
            return False
        if record.task_type in {TaskType.RELAX, TaskType.SCF} and record.metrics.get("converged") is False:
            return False
        return True

    def _skip_blocked_task(self, task: TaskNode, root: Path, index: int, blocked_by: str) -> TaskExecutionRecord:
        task_dir = root / f"{index:02d}_{task.task_type.value}"
        message = f"Skipped {task.task_id} because dependency {blocked_by} did not produce a valid successful result."
        self.notices.append(message)
        return TaskExecutionRecord(
            task_id=task.task_id,
            task_type=task.task_type,
            status=TaskStatus.SKIPPED,
            work_dir=str(task_dir),
            metrics={
                "blocked_by": blocked_by,
                "blocked_reason": message,
                "execution_ok": False,
            },
        )

    def _run_task(self, task: TaskNode, task_dir: Path) -> TaskExecutionRecord:
        from autodft.abacus.runner import run_abacus_task

        if self.run_func is None:
            return run_abacus_task(task, task_dir, self.config.abacus_run)
        return run_abacus_task(task, task_dir, self.config.abacus_run, run_func=self.run_func)


def run_basic_workflow(
    *,
    query: str,
    structure_input: str,
    work_dir: str,
    cfg: Optional[Dict] = None,
    planner: Optional[RulePlanner] = None,
    resolver: Optional[StructureResolver] = None,
    run_func: Optional[RunFunction] = None,
) -> RunSummary:
    """Plan, resolve, and execute the current basic AutoDFT workflow."""

    planner = planner or RulePlanner()
    resolver = resolver or StructureResolver()
    config = WorkflowExecutionConfig.from_mapping(work_dir, cfg or {})
    workflow = planner.plan(query=query, workflow_id="workflow")
    workflow.structure = resolver.resolve(structure_input, work_dir, query=query, config=cfg or {})
    return WorkflowExecutor(config, run_func=run_func).execute(workflow)


__all__ = ["WorkflowExecutor", "run_basic_workflow"]
