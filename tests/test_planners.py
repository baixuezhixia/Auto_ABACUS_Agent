from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autodft.core.enums import BasisType, TaskType  # noqa: E402
from autodft.core.models import TaskNode, WorkflowSpec  # noqa: E402
from autodft.cli.main import ManualTaskPlanner  # noqa: E402
from autodft.planners.normalizer import normalize_workflow  # noqa: E402
from autodft.planners.rule_planner import RulePlanner, infer_task_nodes  # noqa: E402

try:  # noqa: E402
    import pymatgen.core  # noqa: F401
except ImportError:  # noqa: E402
    pymatgen_module = types.ModuleType("pymatgen")
    pymatgen_core_module = types.ModuleType("pymatgen.core")
    pymatgen_core_module.Composition = object
    pymatgen_core_module.Element = object
    pymatgen_core_module.Structure = object
    sys.modules.setdefault("pymatgen", pymatgen_module)
    sys.modules.setdefault("pymatgen.core", pymatgen_core_module)

from pipeline import _resolve_tasks as legacy_resolve_tasks  # noqa: E402
from schema import TaskType as LegacyTaskType  # noqa: E402


def task_types(workflow: WorkflowSpec) -> list[TaskType]:
    return [task.task_type for task in workflow.tasks]


class RulePlannerTests(unittest.TestCase):
    def test_task_inference_from_simple_query(self) -> None:
        inferred = infer_task_nodes("calculate Si band structure and DOS using lcao")

        self.assertEqual([task.task_type for task in inferred], [TaskType.BANDS, TaskType.DOS])
        self.assertTrue(all(task.basis_type == BasisType.LCAO for task in inferred))
        self.assertEqual(inferred[0].params["kline_mode"], "high_symmetry")
        self.assertEqual(inferred[1].params["dos_mode"], "total")
        self.assertEqual(inferred[0].params["basis_type"], "lcao")

    def test_rule_planner_returns_workflow_spec(self) -> None:
        workflow = RulePlanner().plan("relax Si then run bands", workflow_id="wf-test")

        self.assertIsInstance(workflow, WorkflowSpec)
        self.assertEqual(workflow.workflow_id, "wf-test")
        self.assertEqual(task_types(workflow), [TaskType.RELAX, TaskType.SCF, TaskType.BANDS])
        self.assertEqual(workflow.tasks[0].task_id, "t1_relax")
        self.assertEqual(workflow.tasks[1].depends_on, ["t1_relax"])
        self.assertEqual(workflow.tasks[2].depends_on, ["t2_scf"])

    def test_manual_single_task_relax_propagates_lcao_query_hint(self) -> None:
        workflow = ManualTaskPlanner(["relax"]).plan("fully relax the cell with LCAO method")

        self.assertEqual(task_types(workflow), [TaskType.RELAX])
        self.assertEqual(workflow.tasks[0].basis_type, BasisType.LCAO)
        self.assertEqual(workflow.tasks[0].params["basis_type"], "lcao")
        self.assertEqual(workflow.tasks[0].params["calculation"], "cell-relax")

    def test_rule_relax_scf_workflow_propagates_lcao_query_hint(self) -> None:
        workflow = RulePlanner().plan("fully relax the cell with LCAO method, then run scf")

        self.assertEqual(task_types(workflow), [TaskType.RELAX, TaskType.SCF])
        self.assertTrue(all(task.basis_type == BasisType.LCAO for task in workflow.tasks))
        self.assertTrue(all(task.params["basis_type"] == "lcao" for task in workflow.tasks))

    def test_no_basis_query_keeps_default_basis_unset_for_input_defaults(self) -> None:
        workflow = ManualTaskPlanner(["relax"]).plan("fully relax the cell")

        self.assertEqual(task_types(workflow), [TaskType.RELAX])
        self.assertIsNone(workflow.tasks[0].basis_type)
        self.assertNotIn("basis_type", workflow.tasks[0].params)


class WorkflowNormalizerTests(unittest.TestCase):
    def test_dependency_completion_for_bands_dos(self) -> None:
        workflow = normalize_workflow(
            query="bands and dos only",
            tasks=[
                TaskNode(task_id="", task_type=TaskType.BANDS),
                TaskNode(task_id="", task_type=TaskType.DOS),
            ],
        )

        self.assertEqual(task_types(workflow), [TaskType.SCF, TaskType.BANDS, TaskType.DOS])
        self.assertEqual(workflow.tasks[0].depends_on, [])
        self.assertEqual(workflow.tasks[1].depends_on, ["t1_scf"])
        self.assertEqual(workflow.tasks[2].depends_on, ["t1_scf"])

    def test_dependency_completion_for_elastic(self) -> None:
        workflow = normalize_workflow(
            query="elastic constants",
            tasks=[TaskNode(task_id="", task_type=TaskType.ELASTIC)],
        )

        self.assertEqual(task_types(workflow), [TaskType.RELAX, TaskType.SCF, TaskType.ELASTIC])
        self.assertEqual(workflow.tasks[1].depends_on, ["t1_relax"])
        self.assertEqual(workflow.tasks[2].depends_on, ["t2_scf"])

    def test_task_ordering_normalization(self) -> None:
        workflow = normalize_workflow(
            query="dos after relaxation",
            tasks=[
                TaskNode(task_id="", task_type=TaskType.RELAX),
                TaskNode(task_id="", task_type=TaskType.DOS),
            ],
        )

        self.assertEqual(task_types(workflow), [TaskType.RELAX, TaskType.SCF, TaskType.DOS])
        self.assertEqual([task.task_id for task in workflow.tasks], ["t1_relax", "t2_scf", "t3_dos"])
        self.assertEqual(workflow.tasks[1].depends_on, ["t1_relax"])
        self.assertEqual(workflow.tasks[2].depends_on, ["t2_scf"])

    def test_query_task_order_is_preserved_after_dependency_insertion(self) -> None:
        workflow = RulePlanner().plan(
            "fully relax the cell with LCAO method, and then calculate its density of states, band structure, and elastic properties"
        )

        self.assertEqual(
            task_types(workflow),
            [TaskType.RELAX, TaskType.SCF, TaskType.DOS, TaskType.BANDS, TaskType.ELASTIC],
        )
        self.assertEqual(
            [task.task_id for task in workflow.tasks],
            ["t1_relax", "t2_scf", "t3_dos", "t4_bands", "t5_elastic"],
        )
        self.assertEqual(workflow.tasks[0].params["calculation"], "cell-relax")

    def test_basis_hint_propagates_to_inserted_tasks(self) -> None:
        workflow = RulePlanner().plan("calculate bands using lcao")

        self.assertEqual(task_types(workflow), [TaskType.SCF, TaskType.BANDS])
        self.assertTrue(all(task.basis_type == BasisType.LCAO for task in workflow.tasks))
        self.assertTrue(all(task.params["basis_type"] == "lcao" for task in workflow.tasks))


class LegacyTaskPlanningTests(unittest.TestCase):
    def test_legacy_manual_single_task_relax_propagates_lcao_query_hint(self) -> None:
        tasks = legacy_resolve_tasks("fully relax the cell with LCAO method", ["relax"], {"mode": "rule"})

        self.assertEqual([task.task_type for task in tasks], [LegacyTaskType.RELAX])
        self.assertEqual(tasks[0].params["basis_type"], "lcao")
        self.assertEqual(tasks[0].params["calculation"], "cell-relax")

    def test_legacy_inserted_scf_inherits_lcao_query_hint(self) -> None:
        tasks = legacy_resolve_tasks("calculate band structure using LCAO method", None, {"mode": "rule"})

        self.assertEqual([task.task_type for task in tasks], [LegacyTaskType.SCF, LegacyTaskType.BANDS])
        self.assertTrue(all(task.params["basis_type"] == "lcao" for task in tasks))

    def test_legacy_query_order_is_preserved_after_dependency_insertion(self) -> None:
        tasks = legacy_resolve_tasks(
            "fully relax the cell with LCAO method, and then calculate its density of states, band structure, and elastic properties",
            None,
            {"mode": "rule"},
        )

        self.assertEqual(
            [task.task_type for task in tasks],
            [LegacyTaskType.RELAX, LegacyTaskType.SCF, LegacyTaskType.DOS, LegacyTaskType.BANDS, LegacyTaskType.ELASTIC],
        )
        self.assertEqual(tasks[0].params["calculation"], "cell-relax")


if __name__ == "__main__":
    unittest.main()
