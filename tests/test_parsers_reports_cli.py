from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autodft.cli.main import load_config, run_cli  # noqa: E402
from autodft.core.enums import ArtifactType, TaskStatus, TaskType  # noqa: E402
from autodft.core.models import TaskExecutionRecord  # noqa: E402
from autodft.parsers import AbacusLogParser, RunParser  # noqa: E402
from autodft.reports import build_json_report, build_summary_text  # noqa: E402
from autodft.structures.structure_object import make_artifact, make_resolved_structure  # noqa: E402
from autodft.workflows import executor as executor_module  # noqa: E402


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


def fake_abacus_run(cmd, cwd=None, capture_output=False, text=False, check=False):
    task_dir = Path(cwd)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    task_id = next(line for line in input_text.splitlines() if line.startswith("suffix ")).split()[1]
    calculation = next(line for line in input_text.splitlines() if line.startswith("calculation ")).split()[1]
    out_dir = task_dir / f"OUT.{task_id}"
    out_dir.mkdir()
    (out_dir / f"running_{calculation}.log").write_text(
        "converged\nTOTAL ENERGY = -12.25\nE_KS(Ry) : -0.9\nFermi energy = 3.14\n",
        encoding="utf-8",
    )
    if calculation in {"relax", "cell-relax"}:
        (out_dir / "STRU.cif").write_text("# relaxed cif\n", encoding="utf-8")
    if calculation == "scf":
        (out_dir / f"{task_id}-CHARGE-DENSITY.restart").write_text("charge\n", encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 0, stdout=b"ok\n", stderr=b"")


def fake_convert_cif_to_stru(cif_path, output_path, resources, *, basis_type):
    _ = cif_path, resources, basis_type
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(STRU_TEXT.replace("1.0", "2.0", 1), encoding="utf-8")
    return str(Path(output_path).resolve())


class FakeResolver:
    def __init__(self, structure_path: Path) -> None:
        self.structure_path = structure_path

    def resolve(self, structure_input, work_dir, *, query="", config=None):
        return make_resolved_structure(
            provider="fake",
            raw_input=structure_input,
            query=query,
            structure_id="fake-si",
            formula="Si",
            artifacts=[make_artifact(ArtifactType.STRU, self.structure_path, label="base_stru")],
        )


class ParserReportCliTests(unittest.TestCase):
    def test_abacus_log_parser_and_run_parser_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            out_dir = task_dir / "OUT.t1_scf"
            out_dir.mkdir()
            (out_dir / "running_scf.log").write_text(
                "converged\nTOTAL ENERGY = -1.5\nE_KS(Ry) : -0.1\nFermi energy = 0.2\n",
                encoding="utf-8",
            )
            record = TaskExecutionRecord(
                task_id="t1_scf",
                task_type=TaskType.SCF,
                status=TaskStatus.SUCCESS,
                work_dir=str(task_dir),
                return_code=0,
            )

            metrics = AbacusLogParser().parse_task(TaskType.SCF, task_dir, "t1_scf")
            RunParser().update_record(record)

            self.assertEqual(metrics["total_energy_ev"], -1.5)
            self.assertEqual(record.metrics["fermi_energy_ev"], 0.2)
            self.assertTrue(record.metrics["execution_ok"])

    def test_abacus_log_parser_supports_real_scf_smoke_log_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            out_dir = task_dir / "OUT.t1_scf"
            out_dir.mkdir()
            (out_dir / "running_scf.log").write_text(
                """
 PW ALGORITHM --------------- ION=   1  ELEC=   5--------------------------------

 Density error is 7.47854016697e-09
                          Error Threshold = 3.3692492607e-09
----------------------------------------------------------
     Energy           Rydberg                 eV
----------------------------------------------------------
 E_KohnSham     -15.7625413342       -214.4603771057
 E_Fermi        0.4821886604         6.5605132927
----------------------------------------------------------

 charge density convergence is achieved
 final etot is -214.46037711 eV
 EFERMI = 6.5605132927 eV

 --------------------------------------------
 !FINAL_ETOT_IS -214.4603771057349 eV
 --------------------------------------------
""",
                encoding="utf-8",
            )

            metrics = AbacusLogParser().parse_task(TaskType.SCF, task_dir, "t1_scf")

            self.assertTrue(metrics["converged"])
            self.assertAlmostEqual(metrics["total_energy_ev"], -214.4603771057349)
            self.assertEqual(metrics["fermi_energy_ev"], 6.5605132927)

    def test_summary_and_json_reports_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            pseudo_dir = root / "pseudos"
            pseudo_dir.mkdir()
            (pseudo_dir / "Si.upf").write_text("pseudo\n", encoding="utf-8")
            cfg = {
                "abacus": {
                    "executable": "abacus",
                    "run_mode": "local",
                    "np": 1,
                    "pseudo_dir": str(pseudo_dir),
                }
            }

            with contextlib.redirect_stdout(io.StringIO()):
                summary = run_cli(
                    [
                        "--query",
                        "run scf",
                        "--structure",
                        "Si",
                        "--work-dir",
                        str(root / "run"),
                        "--config",
                        str(_write_config(root / "config.yaml", cfg)),
                    ],
                    resolver=FakeResolver(structure_path),
                    run_func=fake_abacus_run,
                )

            payload = build_json_report(summary)
            text = build_summary_text(summary)

            self.assertEqual(payload["query"], "run scf")
            self.assertEqual(payload["execution"][0]["metrics"]["total_energy_ev"], -12.25)
            self.assertIn("Workflow workflow: success", text)
            self.assertIn("t1_scf scf: success", text)

    def test_cli_end_to_end_writes_machine_and_human_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            pseudo_dir = root / "resources" / "pseudos"
            pseudo_dir.mkdir(parents=True)
            (pseudo_dir / "Si.upf").write_text("pseudo\n", encoding="utf-8")
            config_path = root / "config.yaml"
            config_path.write_text(
                """
abacus:
  executable: "abacus"
  run_mode: "local"
  np: 1
  pseudo_dir: "resources/pseudos"
defaults:
  calculation:
    ecutwfc: 40
    kmesh: [2, 2, 2]
MP_API_KEY="from-env-assignment"
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                summary = run_cli(
                    [
                        "--query",
                        "calculate bands",
                        "--structure",
                        "Si",
                        "--work-dir",
                        str(root / "run"),
                        "--config",
                        str(config_path),
                    ],
                    resolver=FakeResolver(structure_path),
                    run_func=fake_abacus_run,
                )

            report_path = root / "run" / "report.json"
            summary_path = root / "run" / "summary.txt"
            report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(summary.status, TaskStatus.SUCCESS)
            self.assertEqual([record.task_id for record in summary.executions], ["t1_scf", "t2_bands"])
            self.assertTrue(report_path.is_file())
            self.assertTrue(summary_path.is_file())
            self.assertEqual(report["status"], "success")
            self.assertEqual(report["report_path"], str(report_path))
            self.assertIn("Workflow workflow: success", stdout.getvalue())

            loaded = load_config(str(config_path))
            self.assertEqual(loaded["MP_API_KEY"], "from-env-assignment")
            self.assertEqual(loaded["abacus"]["pseudo_dir"], str(pseudo_dir.resolve()))

    def test_cli_manual_single_relax_lcao_query_writes_lcao_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            config_path = _write_lcao_config(root)

            with contextlib.redirect_stdout(io.StringIO()):
                run_cli(
                    [
                        "--query",
                        "fully relax the cell with LCAO method",
                        "--structure",
                        "Si",
                        "--work-dir",
                        str(root / "run"),
                        "--config",
                        str(config_path),
                        "--tasks",
                        "relax",
                    ],
                    resolver=FakeResolver(structure_path),
                    run_func=fake_abacus_run,
                )

            input_text = (root / "run" / "01_relax" / "INPUT").read_text(encoding="utf-8")
            kpt_text = (root / "run" / "01_relax" / "KPT").read_text(encoding="utf-8")
            self.assertIn("basis_type lcao", input_text)
            self.assertIn("ks_solver genelpa", input_text)
            self.assertNotIn("\necutrho ", input_text)
            self.assertIn(f"orbital_dir {root / 'orbitals'}", input_text)
            self.assertIn("1 1 1 0 0 0", kpt_text)

    def test_cli_kmesh_override_writes_gamma_only_kpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            config_path = _write_lcao_config(root, kmesh=[4, 4, 4])

            with contextlib.redirect_stdout(io.StringIO()):
                run_cli(
                    [
                        "--query",
                        "run scf with LCAO method",
                        "--structure",
                        "Si",
                        "--work-dir",
                        str(root / "run"),
                        "--config",
                        str(config_path),
                        "--tasks",
                        "scf",
                        "--kmesh",
                        "1,1,1",
                    ],
                    resolver=FakeResolver(structure_path),
                    run_func=fake_abacus_run,
                )

            kpt_text = (root / "run" / "01_scf" / "KPT").read_text(encoding="utf-8")
            input_text = (root / "run" / "01_scf" / "INPUT").read_text(encoding="utf-8")
            self.assertIn("basis_type lcao", input_text)
            self.assertIn("1 1 1 0 0 0", kpt_text)
            self.assertNotIn("4 4 4 0 0 0", kpt_text)

    def test_cli_rule_relax_scf_lcao_query_writes_lcao_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            config_path = _write_lcao_config(root)
            original_converter = executor_module.convert_cif_to_stru

            executor_module.convert_cif_to_stru = fake_convert_cif_to_stru
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    summary = run_cli(
                        [
                            "--query",
                            "fully relax the cell with LCAO method, then run scf",
                            "--structure",
                            "Si",
                            "--work-dir",
                            str(root / "run"),
                            "--config",
                            str(config_path),
                        ],
                        resolver=FakeResolver(structure_path),
                        run_func=fake_abacus_run,
                    )
            finally:
                executor_module.convert_cif_to_stru = original_converter

            self.assertEqual([record.task_id for record in summary.executions], ["t1_relax", "t2_scf"])
            for task_dir in ("01_relax", "02_scf"):
                input_text = (root / "run" / task_dir / "INPUT").read_text(encoding="utf-8")
                self.assertIn("basis_type lcao", input_text)
                self.assertIn("ks_solver genelpa", input_text)
                self.assertNotIn("\necutrho ", input_text)
            self.assertIn(
                "calculation cell-relax",
                (root / "run" / "01_relax" / "INPUT").read_text(encoding="utf-8"),
            )

    def test_cli_preserves_query_task_order_after_dependency_insertion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            config_path = _write_lcao_config(root)
            original_converter = executor_module.convert_cif_to_stru

            executor_module.convert_cif_to_stru = fake_convert_cif_to_stru
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    summary = run_cli(
                        [
                            "--query",
                            "fully relax the cell with LCAO method, and then calculate its density of states, band structure, and elastic properties",
                            "--structure",
                            "Si",
                            "--work-dir",
                            str(root / "run"),
                            "--config",
                            str(config_path),
                        ],
                        resolver=FakeResolver(structure_path),
                        run_func=fake_abacus_run,
                    )
            finally:
                executor_module.convert_cif_to_stru = original_converter

            self.assertEqual(
                [record.task_id for record in summary.executions],
                ["t1_relax", "t2_scf", "t3_dos", "t4_bands", "t5_elastic"],
            )
            self.assertTrue((root / "run" / "01_relax").is_dir())
            self.assertTrue((root / "run" / "02_scf").is_dir())
            self.assertTrue((root / "run" / "03_dos").is_dir())
            self.assertTrue((root / "run" / "04_bands").is_dir())
            self.assertTrue((root / "run" / "05_elastic").is_dir())
            self.assertIn("calculation cell-relax", (root / "run" / "01_relax" / "INPUT").read_text(encoding="utf-8"))


def _write_config(path: Path, cfg: dict) -> Path:
    pseudo_dir = cfg["abacus"]["pseudo_dir"]
    path.write_text(
        f"""abacus:
  executable: "abacus"
  run_mode: "local"
  np: 1
  pseudo_dir: "{pseudo_dir}"
""",
        encoding="utf-8",
    )
    return path


def _write_lcao_config(root: Path, kmesh=None) -> Path:
    pseudo_dir = root / "pseudos"
    orb_dir = root / "orbitals"
    kmesh = kmesh or [1, 1, 1]
    pseudo_dir.mkdir()
    orb_dir.mkdir()
    (pseudo_dir / "Si.upf").write_text("pseudo\n", encoding="utf-8")
    (orb_dir / "Si.orb").write_text("orbital\n", encoding="utf-8")
    config_path = root / "config.yaml"
    config_path.write_text(
        f"""abacus:
  executable: "abacus"
  run_mode: "local"
  np: 1
  pseudo_dir: "{pseudo_dir}"
  orb_dir: "{orb_dir}"
defaults:
  calculation:
    ecutwfc: 40
    kmesh: {kmesh}
""",
        encoding="utf-8",
    )
    return config_path


if __name__ == "__main__":
    unittest.main()
