from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autodft.cli.main import main, run_cli  # noqa: E402
from autodft.core.enums import ArtifactType, TaskStatus  # noqa: E402
from autodft.core.exceptions import StructureResolutionError  # noqa: E402
from autodft.structures import LocalCIFProvider, LocalSTRUProvider, StructureProvider, StructureResolver  # noqa: E402
from autodft.structures.structure_object import make_artifact, make_resolved_structure  # noqa: E402
from autodft.workflows import executor as executor_module  # noqa: E402


STRU_TEXT = """ATOMIC_SPECIES
Si 28.085 Si.upf

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
    _ = cmd, capture_output, text, check
    task_dir = Path(cwd)
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    task_id = next(line for line in input_text.splitlines() if line.startswith("suffix ")).split()[1]
    calculation = next(line for line in input_text.splitlines() if line.startswith("calculation ")).split()[1]
    out_dir = task_dir / f"OUT.{task_id}"
    out_dir.mkdir()
    (out_dir / f"running_{calculation}.log").write_text("converged\nTOTAL ENERGY = -1.0\n", encoding="utf-8")
    if calculation == "scf":
        (out_dir / f"{task_id}-CHARGE-DENSITY.restart").write_text("charge\n", encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 0, stdout=b"ok\n", stderr=b"")


class FakeMPProvider(StructureProvider):
    name = "materials_project"

    def __init__(self, structure_path: Path, *, fail: bool = False) -> None:
        self.structure_path = structure_path
        self.fail = fail
        self.calls: list[str] = []

    def can_resolve(self, structure_input: str) -> bool:
        return True

    def resolve(self, structure_input: str, work_dir: str, *, query: str = "", config=None):
        _ = work_dir, config
        self.calls.append(structure_input)
        if self.fail:
            raise StructureResolutionError(f"No Materials Project entries found for '{structure_input}'")
        return make_resolved_structure(
            provider=self.name,
            raw_input=structure_input,
            query=query,
            structure_id="mp-149",
            formula="Si",
            artifacts=[make_artifact(ArtifactType.STRU, self.structure_path, label="mp_stru")],
            lattice_type="conventional",
        )


class CliStructureResolutionTests(unittest.TestCase):
    def test_cli_local_stru_path_uses_local_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)

            for filename in ("STRU", "input.stru"):
                with self.subTest(filename=filename):
                    structure_path = root / filename
                    structure_path.write_text(STRU_TEXT, encoding="utf-8")
                    with contextlib.redirect_stdout(io.StringIO()):
                        summary = run_cli(
                            [
                                "--query",
                                "run scf",
                                "--structure",
                                str(structure_path),
                                "--work-dir",
                                str(root / f"run-{filename}"),
                                "--config",
                                str(config_path),
                                "--tasks",
                                "scf",
                            ],
                            run_func=fake_abacus_run,
                        )

                    self.assertEqual(summary.status, TaskStatus.SUCCESS)
                    self.assertEqual(summary.workflow.structure.source.provider, "local_stru")
                    self.assertEqual(summary.workflow.structure.source.raw_input, str(structure_path))

    def test_cli_local_cif_path_uses_local_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cif_path = root / "local_si.cif"
            cif_path.write_text("# minimal CIF fixture; conversion is stubbed in this CLI test\n", encoding="utf-8")
            config_path = _write_config(root)
            original_converter = executor_module.convert_cif_to_stru

            def fake_convert_cif_to_stru(cif_input, output_path, resources, *, basis_type):
                _ = cif_input, resources, basis_type
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text(STRU_TEXT, encoding="utf-8")
                return str(Path(output_path).resolve())

            executor_module.convert_cif_to_stru = fake_convert_cif_to_stru
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    summary = run_cli(
                        [
                            "--query",
                            "run scf",
                            "--structure",
                            str(cif_path),
                            "--work-dir",
                            str(root / "run"),
                            "--config",
                            str(config_path),
                            "--tasks",
                            "scf",
                        ],
                        run_func=fake_abacus_run,
                    )
            finally:
                executor_module.convert_cif_to_stru = original_converter

            self.assertEqual(summary.status, TaskStatus.SUCCESS)
            self.assertEqual(summary.workflow.structure.source.provider, "local_cif")
            self.assertTrue((root / "run" / "materials_project" / "local_si.STRU").is_file())

    def test_cli_formula_and_material_id_fall_through_to_mp_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            config_path = _write_config(root)
            mp_provider = FakeMPProvider(structure_path)
            resolver = StructureResolver(providers=[LocalCIFProvider(), LocalSTRUProvider(), mp_provider])

            for structure_input in ("Si", "mp-149"):
                with self.subTest(structure_input=structure_input):
                    with contextlib.redirect_stdout(io.StringIO()):
                        summary = run_cli(
                            [
                                "--query",
                                "run scf",
                                "--structure",
                                structure_input,
                                "--work-dir",
                                str(root / f"run-{structure_input}"),
                                "--config",
                                str(config_path),
                                "--tasks",
                                "scf",
                            ],
                            resolver=resolver,
                            run_func=fake_abacus_run,
                        )
                    self.assertEqual(summary.status, TaskStatus.SUCCESS)
                    self.assertEqual(summary.workflow.structure.source.provider, "materials_project")

            self.assertEqual(mp_provider.calls, ["Si", "mp-149"])

    def test_cli_missing_local_file_message_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            missing = root / "missing.cif"

            with self.assertRaises(SystemExit) as ctx:
                with contextlib.redirect_stdout(io.StringIO()):
                    main(
                        [
                            "--query",
                            "run scf",
                            "--structure",
                            str(missing),
                            "--work-dir",
                            str(root / "run"),
                            "--config",
                            str(config_path),
                            "--tasks",
                            "scf",
                        ],
                        run_func=fake_abacus_run,
                    )

            message = str(ctx.exception)
            self.assertIn("Error: Failed to resolve structure", message)
            self.assertIn("Local CIF file not found", message)
            self.assertIn("missing.cif", message)

    def test_cli_unsupported_local_file_message_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            unsupported = root / "structure.xyz"
            unsupported.write_text("not supported\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as ctx:
                with contextlib.redirect_stdout(io.StringIO()):
                    main(
                        [
                            "--query",
                            "run scf",
                            "--structure",
                            str(unsupported),
                            "--work-dir",
                            str(root / "run"),
                            "--config",
                            str(config_path),
                            "--tasks",
                            "scf",
                        ],
                        run_func=fake_abacus_run,
                    )

            message = str(ctx.exception)
            self.assertIn("Error: Unsupported local structure file", message)
            self.assertIn("Supported local formats are .cif and ABACUS STRU/.stru files", message)

    def test_cli_unresolved_mp_input_message_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structure_path = root / "base.STRU"
            structure_path.write_text(STRU_TEXT, encoding="utf-8")
            config_path = _write_config(root)
            resolver = StructureResolver(providers=[FakeMPProvider(structure_path, fail=True)])

            with self.assertRaises(SystemExit) as ctx:
                with contextlib.redirect_stdout(io.StringIO()):
                    main(
                        [
                            "--query",
                            "run scf",
                            "--structure",
                            "Xx",
                            "--work-dir",
                            str(root / "run"),
                            "--config",
                            str(config_path),
                            "--tasks",
                            "scf",
                        ],
                        resolver=resolver,
                        run_func=fake_abacus_run,
                    )

            message = str(ctx.exception)
            self.assertIn("Error: Failed to resolve structure 'Xx'", message)
            self.assertIn("No Materials Project entries found for 'Xx'", message)


def _write_config(root: Path) -> Path:
    pseudo_dir = root / "pseudos"
    pseudo_dir.mkdir()
    (pseudo_dir / "Si.upf").write_text("pseudo\n", encoding="utf-8")
    config_path = root / "config.yaml"
    config_path.write_text(
        f"""abacus:
  executable: "abacus"
  run_mode: "local"
  np: 1
  pseudo_dir: "{pseudo_dir}"
defaults:
  calculation:
    ecutwfc: 40
    kmesh: [1, 1, 1]
""",
        encoding="utf-8",
    )
    return config_path


if __name__ == "__main__":
    unittest.main()
