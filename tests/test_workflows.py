from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autodft.core.enums import ArtifactType, TaskStatus, TaskType  # noqa: E402
from autodft.core.exceptions import PlanningError  # noqa: E402
from autodft.core.models import TaskNode, WorkflowSpec  # noqa: E402
from autodft.planners.rule_planner import RulePlanner  # noqa: E402
from autodft.structures.structure_object import make_artifact, make_resolved_structure  # noqa: E402
from autodft.workflows.artifact_store import ArtifactStore  # noqa: E402
from autodft.workflows.dependency_graph import DependencyGraph  # noqa: E402
from autodft.workflows import executor as executor_module  # noqa: E402
from autodft.workflows.executor import WorkflowExecutor, run_basic_workflow  # noqa: E402
from autodft.workflows.spec import WorkflowExecutionConfig  # noqa: E402


STRU_TEXT = """ATOMIC_SPECIES
Si 28.085 old.upf

LATTICE_CONSTANT
1.0

LATTICE_VECTORS
1.0 0.0 0.0
0.0 1.0 0.0
0.0 0.0 1.0

ATOMIC_POSITIONS
Direct
Si
0.0
1
0.0 0.0 0.0 0 0 0
"""


def write_basic_inputs(root: Path) -> dict:
    pseudo_dir = root / "pseudos"
    pseudo_dir.mkdir()
    (pseudo_dir / "Si.upf").write_text("pseudo\n", encoding="utf-8")
    structure_path = root / "base.STRU"
    structure_path.write_text(STRU_TEXT, encoding="utf-8")
    return {
        "structure_path": structure_path,
        "cfg": {
            "abacus": {
                "executable": "abacus",
                "run_mode": "local",
                "np": 1,
                "pseudo_dir": str(pseudo_dir),
            },
            "defaults": {
                "calculation": {
                    "ecutwfc": 60,
                    "kmesh": [2, 2, 2],
                }
            },
        },
    }


def make_fake_structure(structure_path: Path):
    return make_resolved_structure(
        provider="fake",
        raw_input="Si",
        query="",
        structure_id="fake-si",
        formula="Si",
        artifacts=[make_artifact(ArtifactType.STRU, structure_path, label="base_stru")],
    )


class FakeResolver:
    def __init__(self, structure_path: Path) -> None:
        self.structure_path = structure_path

    def resolve(self, structure_input, work_dir, *, query="", config=None):
        return make_fake_structure(self.structure_path)


def fake_abacus_run(cmd, cwd=None, capture_output=False, text=False, check=False):
    task_dir = Path(cwd)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    suffix_line = next(line for line in input_text.splitlines() if line.startswith("suffix "))
    task_id = suffix_line.split()[1]
    calculation = next(line for line in input_text.splitlines() if line.startswith("calculation ")).split()[1]
    out_dir = task_dir / f"OUT.{task_id}"
    out_dir.mkdir()
    (out_dir / f"running_{calculation}.log").write_text(
        "converged\nTOTAL ENERGY = -10.5\nFermi energy = 1.2\n",
        encoding="utf-8",
    )
    if calculation == "scf":
        (out_dir / f"{task_id}-CHARGE-DENSITY.restart").write_text("charge\n", encoding="utf-8")
        (out_dir / "onsite.dm").write_text("onsite\n", encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 0, stdout=f"ran {task_id}\n".encode(), stderr=b"")


def fake_scf_without_charge(cmd, cwd=None, capture_output=False, text=False, check=False):
    task_dir = Path(cwd)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    task_id = next(line for line in input_text.splitlines() if line.startswith("suffix ")).split()[1]
    calculation = next(line for line in input_text.splitlines() if line.startswith("calculation ")).split()[1]
    if calculation != "scf":
        raise AssertionError("Downstream task should have been skipped when SCF charge files are missing.")
    out_dir = task_dir / f"OUT.{task_id}"
    out_dir.mkdir()
    (out_dir / "running_scf.log").write_text(
        "charge density convergence is achieved\nfinal etot is -10.5 eV\n",
        encoding="utf-8",
    )
    return subprocess.CompletedProcess(cmd, 0, stdout=f"ran {task_id}\n".encode(), stderr=b"")


def fake_failed_scf(cmd, cwd=None, capture_output=False, text=False, check=False):
    task_dir = Path(cwd)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    task_id = next(line for line in input_text.splitlines() if line.startswith("suffix ")).split()[1]
    calculation = next(line for line in input_text.splitlines() if line.startswith("calculation ")).split()[1]
    if calculation != "scf":
        raise AssertionError("Downstream task should have been skipped after failed SCF.")
    out_dir = task_dir / f"OUT.{task_id}"
    out_dir.mkdir()
    (out_dir / "running_scf.log").write_text("scf failed\n", encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 1, stdout=b"failed scf\n", stderr=b"scf error\n")


def fake_relax_then_scf_success(cmd, cwd=None, capture_output=False, text=False, check=False):
    task_dir = Path(cwd)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    task_id = next(line for line in input_text.splitlines() if line.startswith("suffix ")).split()[1]
    calculation = next(line for line in input_text.splitlines() if line.startswith("calculation ")).split()[1]
    out_dir = task_dir / f"OUT.{task_id}"
    out_dir.mkdir()
    (out_dir / f"running_{calculation}.log").write_text(
        "charge density convergence is achieved\nfinal etot is -10.5 eV\n",
        encoding="utf-8",
    )
    if calculation in {"relax", "cell-relax"}:
        (out_dir / "STRU.cif").write_text("# relaxed cif\n", encoding="utf-8")
    if calculation == "scf":
        (out_dir / f"{task_id}-CHARGE-DENSITY.restart").write_text("charge\n", encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 0, stdout=f"ran {task_id}\n".encode(), stderr=b"")


def fake_failed_relax_writes_stru_cif(cmd, cwd=None, capture_output=False, text=False, check=False):
    task_dir = Path(cwd)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    task_id = next(line for line in input_text.splitlines() if line.startswith("suffix ")).split()[1]
    calculation = next(line for line in input_text.splitlines() if line.startswith("calculation ")).split()[1]
    if calculation != "relax":
        raise AssertionError("Downstream task should have been skipped after failed relax.")
    out_dir = task_dir / f"OUT.{task_id}"
    out_dir.mkdir()
    (out_dir / "running_relax.log").write_text("relax failed\n", encoding="utf-8")
    (out_dir / "STRU.cif").write_text("# invalid relaxed cif from failed run\n", encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 1, stdout=b"failed relax\n", stderr=b"relax error\n")


class DependencyGraphTests(unittest.TestCase):
    def test_dependency_graph_preserves_dependency_order(self) -> None:
        workflow = RulePlanner().plan("relax then bands")

        ordered = DependencyGraph(workflow).execution_order()

        self.assertEqual([task.task_id for task in ordered], ["t1_relax", "t2_scf", "t3_bands"])

    def test_dependency_graph_reports_missing_dependency(self) -> None:
        workflow = RulePlanner().plan("scf")
        workflow.tasks[0].depends_on = ["missing"]

        with self.assertRaises(PlanningError) as ctx:
            DependencyGraph(workflow)

        self.assertIn("depends on unknown task 'missing'", str(ctx.exception))


class ArtifactStoreTests(unittest.TestCase):
    def test_artifact_store_filters_by_task_and_type(self) -> None:
        store = ArtifactStore()
        artifact = make_artifact(ArtifactType.STRU, "/tmp/a.STRU")
        artifact.task_id = "t1_scf"

        store.add(artifact)

        self.assertEqual(store.by_task("t1_scf"), [artifact])
        self.assertEqual(store.first(ArtifactType.STRU, task_id="t1_scf"), artifact)
        self.assertIsNone(store.first(ArtifactType.CIF))


class WorkflowExecutorTests(unittest.TestCase):
    def test_executor_runs_workflow_and_stages_dependency_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = write_basic_inputs(root)
            workflow = RulePlanner().plan("calculate bands and dos")
            workflow.structure = make_fake_structure(inputs["structure_path"])
            config = WorkflowExecutionConfig.from_mapping(str(root / "run"), inputs["cfg"])

            summary = WorkflowExecutor(config, run_func=fake_abacus_run).execute(workflow)

            self.assertEqual(summary.status, TaskStatus.SUCCESS)
            self.assertEqual([record.task_id for record in summary.executions], ["t1_scf", "t2_bands", "t3_dos"])
            self.assertEqual(summary.executions[0].metrics["total_energy_ev"], -10.5)
            self.assertIn("init_chg file", (root / "run" / "02_bands" / "INPUT").read_text(encoding="utf-8"))
            self.assertIn("read_file_dir READ_CHG", (root / "run" / "02_bands" / "INPUT").read_text(encoding="utf-8"))
            self.assertIn("init_chg file", (root / "run" / "03_dos" / "INPUT").read_text(encoding="utf-8"))
            self.assertIn("read_file_dir READ_CHG", (root / "run" / "03_dos" / "INPUT").read_text(encoding="utf-8"))
            self.assertTrue((root / "run" / "02_bands" / "READ_CHG" / "t2_bands-CHARGE-DENSITY.restart").is_file())
            self.assertTrue((root / "run" / "02_bands" / "READ_CHG" / "onsite.dm").is_file())
            self.assertTrue((root / "run" / "03_dos" / "READ_CHG" / "t3_dos-CHARGE-DENSITY.restart").is_file())
            self.assertTrue((root / "run" / "03_dos" / "READ_CHG" / "onsite.dm").is_file())
            self.assertTrue(any("Using SCF structure" in notice for notice in summary.notices))
            self.assertTrue(any("Using SCF charge artifacts" in notice for notice in summary.notices))
            self.assertTrue((root / "run" / "report.json").is_file())
            self.assertEqual(summary.report_path, str(root / "run" / "report.json"))

    def test_scf_to_elastic_uses_structure_and_optional_charge_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = write_basic_inputs(root)
            workflow = WorkflowSpec(
                workflow_id="wf",
                query="scf elastic",
                tasks=[
                    TaskNode(task_id="t1_scf", task_type=TaskType.SCF),
                    TaskNode(task_id="t2_elastic", task_type=TaskType.ELASTIC, depends_on=["t1_scf"]),
                ],
            )
            workflow.structure = make_fake_structure(inputs["structure_path"])
            config = WorkflowExecutionConfig.from_mapping(str(root / "run"), inputs["cfg"])

            summary = WorkflowExecutor(config, run_func=fake_abacus_run).execute(workflow)

            self.assertEqual(summary.status, TaskStatus.SUCCESS)
            self.assertEqual([record.task_id for record in summary.executions], ["t1_scf", "t2_elastic"])
            elastic_input = (root / "run" / "02_elastic" / "INPUT").read_text(encoding="utf-8")
            self.assertIn("init_chg file", elastic_input)
            self.assertIn("read_file_dir READ_CHG", elastic_input)
            self.assertTrue((root / "run" / "02_elastic" / "READ_CHG" / "t2_elastic-CHARGE-DENSITY.restart").is_file())
            self.assertTrue((root / "run" / "02_elastic" / "READ_CHG" / "onsite.dm").is_file())
            self.assertEqual(
                (root / "run" / "01_scf" / "STRU").read_text(encoding="utf-8"),
                (root / "run" / "02_elastic" / "STRU").read_text(encoding="utf-8"),
            )

    def test_missing_scf_charge_blocks_bands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = write_basic_inputs(root)
            workflow = RulePlanner().plan("scf bands")
            workflow.structure = make_fake_structure(inputs["structure_path"])
            config = WorkflowExecutionConfig.from_mapping(str(root / "run"), inputs["cfg"])

            summary = WorkflowExecutor(config, run_func=fake_scf_without_charge).execute(workflow)

            self.assertEqual(summary.status, TaskStatus.FAILED)
            self.assertEqual([record.status for record in summary.executions], [TaskStatus.SUCCESS, TaskStatus.SKIPPED])
            self.assertEqual(summary.executions[1].metrics["blocked_by"], "t1_scf")
            self.assertFalse((root / "run" / "02_bands" / "INPUT").exists())
            self.assertTrue(any("did not produce reusable SCF charge-density files" in notice for notice in summary.notices))

    def test_failed_scf_blocks_downstream_dos_bands_elastic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = write_basic_inputs(root)
            workflow = WorkflowSpec(
                workflow_id="wf",
                query="scf dos bands elastic",
                tasks=[
                    TaskNode(task_id="t1_scf", task_type=TaskType.SCF),
                    TaskNode(task_id="t2_dos", task_type=TaskType.DOS, depends_on=["t1_scf"]),
                    TaskNode(task_id="t3_bands", task_type=TaskType.BANDS, depends_on=["t1_scf"]),
                    TaskNode(task_id="t4_elastic", task_type=TaskType.ELASTIC, depends_on=["t1_scf"]),
                ],
            )
            workflow.structure = make_fake_structure(inputs["structure_path"])
            config = WorkflowExecutionConfig.from_mapping(str(root / "run"), inputs["cfg"])

            summary = WorkflowExecutor(config, run_func=fake_failed_scf).execute(workflow)

            self.assertEqual(summary.status, TaskStatus.FAILED)
            self.assertEqual(
                [record.status for record in summary.executions],
                [TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.SKIPPED, TaskStatus.SKIPPED],
            )
            self.assertTrue(all(record.metrics.get("blocked_by") == "t1_scf" for record in summary.executions[1:]))

    def test_successful_relax_structure_is_propagated_to_scf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = write_basic_inputs(root)
            workflow = RulePlanner().plan("relax scf")
            workflow.structure = make_fake_structure(inputs["structure_path"])
            config = WorkflowExecutionConfig.from_mapping(str(root / "run"), inputs["cfg"])
            original_converter = executor_module.convert_cif_to_stru
            converted_sources = []

            def fake_convert_cif_to_stru(cif_path, output_path, resources, *, basis_type):
                converted_sources.append(Path(cif_path))
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text(STRU_TEXT.replace("1.0", "2.0", 1), encoding="utf-8")
                return str(Path(output_path).resolve())

            executor_module.convert_cif_to_stru = fake_convert_cif_to_stru
            try:
                summary = WorkflowExecutor(config, run_func=fake_relax_then_scf_success).execute(workflow)
            finally:
                executor_module.convert_cif_to_stru = original_converter

            self.assertEqual([record.status for record in summary.executions], [TaskStatus.SUCCESS, TaskStatus.SUCCESS])
            self.assertTrue(any("Using relaxed structure" in notice for notice in summary.notices))
            self.assertTrue((root / "run" / "relaxed_structures" / "t1_relax.STRU").is_file())
            self.assertEqual(converted_sources, [root / "run" / "01_relax" / "OUT.t1_relax" / "STRU.cif"])
            self.assertIn("LATTICE_CONSTANT\n2.0", (root / "run" / "02_scf" / "STRU").read_text(encoding="utf-8"))

    def test_failed_relax_does_not_propagate_relaxed_structure_and_skips_scf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = write_basic_inputs(root)
            workflow = RulePlanner().plan("relax scf")
            workflow.structure = make_fake_structure(inputs["structure_path"])
            config = WorkflowExecutionConfig.from_mapping(str(root / "run"), inputs["cfg"])

            summary = WorkflowExecutor(config, run_func=fake_failed_relax_writes_stru_cif).execute(workflow)

            self.assertEqual(summary.status, TaskStatus.FAILED)
            self.assertEqual([record.task_id for record in summary.executions], ["t1_relax", "t2_scf"])
            self.assertEqual(summary.executions[0].status, TaskStatus.FAILED)
            self.assertEqual(summary.executions[1].status, TaskStatus.SKIPPED)
            self.assertEqual(summary.executions[1].metrics["blocked_by"], "t1_relax")
            self.assertFalse((root / "run" / "relaxed_structures" / "t1_relax.STRU").exists())
            self.assertFalse((root / "run" / "02_scf" / "INPUT").exists())
            self.assertFalse(any("Using relaxed structure" in notice for notice in summary.notices))
            self.assertTrue(any("Skipped t2_scf because dependency t1_relax" in notice for notice in summary.notices))

    def test_run_basic_workflow_plans_resolves_and_executes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = write_basic_inputs(root)

            summary = run_basic_workflow(
                query="run scf",
                structure_input="Si",
                work_dir=str(root / "run"),
                cfg=inputs["cfg"],
                resolver=FakeResolver(inputs["structure_path"]),
                run_func=fake_abacus_run,
            )

            self.assertEqual(summary.status, TaskStatus.SUCCESS)
            self.assertEqual(len(summary.executions), 1)
            self.assertEqual(summary.workflow.structure.structure_id, "fake-si")


if __name__ == "__main__":
    unittest.main()
