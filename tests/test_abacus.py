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

from autodft.abacus.input_generator import generate_abacus_inputs  # noqa: E402
from autodft.abacus.presets import AbacusInputPreset, normalize_kmesh  # noqa: E402
from autodft.abacus.resources import AbacusResourceConfig  # noqa: E402
from autodft.abacus.runner import AbacusRunConfig, build_command, run_abacus_task  # noqa: E402
from autodft.abacus.structure_io import convert_cif_to_stru  # noqa: E402
from autodft.core.enums import ArtifactType, TaskStatus, TaskType  # noqa: E402
from autodft.core.models import TaskNode  # noqa: E402

try:  # noqa: E402
    from pymatgen.core import Lattice, Structure
except ImportError:  # noqa: E402
    Lattice = None
    Structure = None


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
2
0.0 0.0 0.0 0 0 0
0.25 0.25 0.25 0 0 0
"""


def write_resources(root: Path) -> AbacusResourceConfig:
    pseudo_dir = root / "pseudos"
    orb_dir = root / "orbitals"
    pseudo_dir.mkdir()
    orb_dir.mkdir()
    (pseudo_dir / "Si.upf").write_text("pseudo\n", encoding="utf-8")
    (orb_dir / "Si.orb").write_text("orbital\n", encoding="utf-8")
    return AbacusResourceConfig(pseudo_dir=str(pseudo_dir), orb_dir=str(orb_dir))


def write_realistic_si_resources(root: Path) -> AbacusResourceConfig:
    pseudo_dir = root / "Pseudopotential"
    orb_dir = root / "StandardOrbitals"
    pseudo_dir.mkdir()
    orb_dir.mkdir()
    (pseudo_dir / "Si_ONCV_PBE-1.0.upf").write_text("pseudo\n", encoding="utf-8")
    (orb_dir / "Si_gga_7au_100Ry_2s2p1d.orb").write_text("orbital\n", encoding="utf-8")
    return AbacusResourceConfig(pseudo_dir=str(pseudo_dir), orb_dir=str(orb_dir))


class AbacusInputGenerationTests(unittest.TestCase):
    def test_kmesh_normalization_accepts_debug_string_forms(self) -> None:
        self.assertEqual(normalize_kmesh("1,1,1"), [1, 1, 1])
        self.assertEqual(normalize_kmesh("1x2x3"), [1, 2, 3])
        self.assertEqual(AbacusInputPreset.from_mapping({"kmesh": "2 2 2"}).kmesh, [2, 2, 2])

    def test_generate_pw_scf_input_kpt_stru_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            preset = AbacusInputPreset.from_mapping(
                {
                    "ecutwfc": 60,
                    "kmesh": [4, 4, 4],
                    "smearing_method": "fixed",
                    "scf_thr": 1e-9,
                    "scf_nmax": 1,
                    "out_chg": 99,
                }
            )

            generated = generate_abacus_inputs(
                TaskNode(task_id="t1_scf", task_type=TaskType.SCF),
                root / "01_scf",
                structure_path,
                preset=preset,
                resources=resources,
            )

            expected_input = f"""INPUT_PARAMETERS
suffix t1_scf
stru_file STRU
kpoint_file KPT
pseudo_dir {resources.pseudo_dir}
basis_type pw
calculation scf
ecutwfc 60
scf_thr 1e-09
scf_nmax 1
ks_solver cg
nspin 1
symmetry 1
out_level ie
out_stru 0
smearing_method fixed
out_chg 1
"""
            expected_kpt = """K_POINTS
0
Gamma
4 4 4 0 0 0
"""
            self.assertEqual(generated.input_path.read_text(encoding="utf-8"), expected_input)
            self.assertEqual(generated.kpt_path.read_text(encoding="utf-8"), expected_kpt)
            self.assertNotIn("\necutrho ", generated.input_path.read_text(encoding="utf-8"))
            stru = generated.stru_path.read_text(encoding="utf-8")
            self.assertIn("Si 28.085 Si.upf upf201", stru)
            self.assertIn("0.0 0.0 0.0 0 0 0", stru)
            self.assertNotIn("NUMERICAL_ORBITAL", stru)

    def test_generate_pw_respects_explicit_ecutrho_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t1_scf", task_type=TaskType.SCF),
                root / "01_scf",
                structure_path,
                preset=AbacusInputPreset.from_mapping({"ecutrho": 480}),
                resources=resources,
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            self.assertIn("basis_type pw", input_text)
            self.assertIn("ecutwfc 80", input_text)
            self.assertIn("ecutrho 480", input_text)

    def test_generate_lcao_stru_adds_orbital_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t1_scf", task_type=TaskType.SCF, params={"basis_type": "lcao"}),
                root / "01_scf",
                structure_path,
                resources=resources,
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            self.assertIn("basis_type lcao", input_text)
            self.assertIn("ks_solver genelpa", input_text)
            self.assertNotIn("\necutrho ", input_text)
            self.assertIn(f"orbital_dir {Path(resources.orb_dir).resolve()}", input_text)
            self.assertIn("NUMERICAL_ORBITAL\nSi.orb", generated.stru_path.read_text(encoding="utf-8"))

    def test_generate_lcao_resolves_realistic_si_orbital_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_realistic_si_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t1_relax", task_type=TaskType.RELAX, params={"basis_type": "lcao"}),
                root / "01_relax",
                structure_path,
                resources=resources,
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            stru_text = generated.stru_path.read_text(encoding="utf-8")
            self.assertIn("calculation relax", input_text)
            self.assertIn("out_stru 1", input_text)
            self.assertIn("out_chg 0", input_text)
            self.assertIn(f"orbital_dir {Path(resources.orb_dir).resolve()}", input_text)
            self.assertIn("NUMERICAL_ORBITAL\nSi_gga_7au_100Ry_2s2p1d.orb", stru_text)
            self.assertIn("0.0 0.0 0.0 1 1 1", stru_text)
            self.assertIn("0.25 0.25 0.25 1 1 1", stru_text)
            self.assertNotIn("0.0 0.0 0.0 0 0 0", stru_text)

    def test_generate_full_relax_uses_cell_relax_calculation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t1_relax", task_type=TaskType.RELAX, params={"calculation": "cell-relax"}),
                root / "01_relax",
                structure_path,
                resources=resources,
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            self.assertIn("calculation cell-relax", input_text)
            self.assertIn("out_stru 1", input_text)
            self.assertIn("out_chg 0", input_text)

    def test_generate_lcao_respects_explicit_ks_solver_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t1_scf", task_type=TaskType.SCF, params={"basis_type": "lcao"}),
                root / "01_scf",
                structure_path,
                preset=AbacusInputPreset.from_mapping({"ks_solver": "elpa"}),
                resources=resources,
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            self.assertIn("basis_type lcao", input_text)
            self.assertIn("ks_solver elpa", input_text)

    def test_generate_lcao_respects_explicit_ecutrho_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t1_scf", task_type=TaskType.SCF, params={"basis_type": "lcao"}),
                root / "01_scf",
                structure_path,
                preset=AbacusInputPreset.from_mapping({"ecutrho": 400}),
                resources=resources,
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            self.assertIn("basis_type lcao", input_text)
            self.assertIn("ecutrho 400", input_text)

    def test_generate_bands_stages_charge_and_uses_line_kpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            dep_out = root / "01_scf" / "OUT.t1_scf"
            dep_out.mkdir(parents=True)
            (dep_out / "t1_scf-CHARGE-DENSITY.restart").write_text("charge\n", encoding="utf-8")
            (dep_out / "onsite.dm").write_text("onsite\n", encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t2_bands", task_type=TaskType.BANDS),
                root / "02_bands",
                structure_path,
                resources=resources,
                dependency_task_dir=root / "01_scf",
                dependency_task_id="t1_scf",
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            self.assertIn("calculation nscf", input_text)
            self.assertIn("symmetry 0", input_text)
            self.assertIn("init_chg file", input_text)
            self.assertIn("read_file_dir READ_CHG", input_text)
            self.assertIn("out_band 1", input_text)
            self.assertTrue((root / "02_bands" / "READ_CHG" / "t2_bands-CHARGE-DENSITY.restart").is_file())
            self.assertTrue((root / "02_bands" / "READ_CHG" / "onsite.dm").is_file())
            self.assertEqual(
                generated.kpt_path.read_text(encoding="utf-8").splitlines()[:3],
                ["K_POINTS", "4", "Line_Cartesian"],
            )

    def test_generate_elastic_uses_optional_scf_charge_handoff_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            dep_out = root / "01_scf" / "OUT.t1_scf"
            dep_out.mkdir(parents=True)
            (dep_out / "t1_scf-CHARGE-DENSITY.restart").write_text("charge\n", encoding="utf-8")
            (dep_out / "onsite.dm").write_text("onsite\n", encoding="utf-8")

            generated = generate_abacus_inputs(
                TaskNode(task_id="t2_elastic", task_type=TaskType.ELASTIC),
                root / "02_elastic",
                structure_path,
                resources=resources,
                dependency_task_dir=root / "01_scf",
                dependency_task_id="t1_scf",
            )

            input_text = generated.input_path.read_text(encoding="utf-8")
            self.assertIn("calculation scf", input_text)
            self.assertIn("init_chg file", input_text)
            self.assertIn("read_file_dir READ_CHG", input_text)
            self.assertTrue((root / "02_elastic" / "READ_CHG" / "t2_elastic-CHARGE-DENSITY.restart").is_file())
            self.assertTrue((root / "02_elastic" / "READ_CHG" / "onsite.dm").is_file())

@unittest.skipIf(Structure is None, "pymatgen is not installed")
class AbacusStructureIOTests(unittest.TestCase):
    def test_convert_cif_to_stru_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = write_resources(root)
            structure = Structure(
                Lattice.cubic(5.43),
                ["Si", "Si"],
                [[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
            )
            cif_path = root / "si.cif"
            stru_path = root / "si.STRU"
            structure.to(filename=str(cif_path))

            result_path = convert_cif_to_stru(cif_path, stru_path, resources)

            self.assertEqual(result_path, str(stru_path.resolve()))
            rendered = stru_path.read_text(encoding="utf-8")
            self.assertIn("ATOMIC_SPECIES\nSi ", rendered)
            self.assertIn("Si.upf upf201", rendered)
            self.assertIn("LATTICE_CONSTANT\n1.889726125457828", rendered)
            self.assertIn("ATOMIC_POSITIONS\nDirect\nSi\n0.0\n2", rendered)


class AbacusRunnerTests(unittest.TestCase):
    def test_build_command_supports_local_and_mpirun(self) -> None:
        task_dir = Path("/tmp/abacus-task")

        local_cmd, local_cwd = build_command(
            task_dir=task_dir,
            executable="abacus",
            run_mode="local",
            np=4,
            use_hwthread_cpus=False,
            oversubscribe=False,
        )
        mpi_cmd, mpi_cwd = build_command(
            task_dir=task_dir,
            executable="abacus",
            run_mode="mpirun",
            np=4,
            use_hwthread_cpus=True,
            oversubscribe=True,
        )

        self.assertEqual(local_cmd, ["abacus"])
        self.assertEqual(local_cwd, str(task_dir))
        self.assertEqual(mpi_cmd, ["mpirun", "--allow-run-as-root", "--use-hwthread-cpus", "--oversubscribe", "-np", "4", "abacus"])
        self.assertEqual(mpi_cwd, str(task_dir))

    def test_runner_uses_injected_subprocess_and_writes_record(self) -> None:
        calls = []

        def fake_run(cmd, cwd=None, capture_output=False, text=False, check=False):
            calls.append(
                {
                    "cmd": cmd,
                    "cwd": cwd,
                    "capture_output": capture_output,
                    "text": text,
                    "check": check,
                }
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=b"ok\n", stderr=b"")

        with tempfile.TemporaryDirectory() as tmp:
            task = TaskNode(task_id="t1_scf", task_type=TaskType.SCF)
            record = run_abacus_task(
                task,
                tmp,
                AbacusRunConfig(executable="abacus", run_mode="local", np=1),
                run_func=fake_run,
            )

            self.assertEqual(record.status, TaskStatus.SUCCESS)
            self.assertEqual(record.return_code, 0)
            self.assertEqual(record.stdout_tail, "ok\n")
            self.assertEqual(calls[0]["cmd"], ["abacus"])
            self.assertTrue((Path(tmp) / "run.log").is_file())
            self.assertTrue(any(artifact.artifact_type == ArtifactType.RUN_LOG for artifact in record.artifacts))


if __name__ == "__main__":
    unittest.main()
