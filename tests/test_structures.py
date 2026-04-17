from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autodft.core.enums import ArtifactType  # noqa: E402
from autodft.core.exceptions import StructureResolutionError  # noqa: E402
from autodft.structures.base import StructureProvider  # noqa: E402
from autodft.structures.local_cif_provider import LocalCIFProvider  # noqa: E402
from autodft.structures.local_stru_provider import LocalSTRUProvider  # noqa: E402
from autodft.structures.mp_provider import MaterialsProjectProvider  # noqa: E402
from autodft.structures.resolver import StructureResolver  # noqa: E402
from autodft.structures.structure_object import artifact_path  # noqa: E402


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


class FakeStructure:
    def __init__(self, material_id: str) -> None:
        self.material_id = material_id

    def to(self, filename: str) -> None:
        Path(filename).write_text(f"# CIF for {self.material_id}\n", encoding="utf-8")


class FakeSummaryClient:
    def __init__(self, docs_by_material_id, docs_by_formula) -> None:
        self.docs_by_material_id = docs_by_material_id
        self.docs_by_formula = docs_by_formula
        self.calls = []

    def search(self, *, material_ids=None, formula=None, fields=None):
        self.calls.append({"material_ids": material_ids, "formula": formula, "fields": fields})
        if material_ids:
            return self.docs_by_material_id.get(material_ids[0], [])
        return self.docs_by_formula.get(formula, [])


class FakeMPClient:
    def __init__(self, docs_by_material_id=None, docs_by_formula=None) -> None:
        self.summary = FakeSummaryClient(docs_by_material_id or {}, docs_by_formula or {})
        self.materials = SimpleNamespace(summary=self.summary)
        self.requested_structures = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_structure_by_material_id(self, material_id: str, conventional_unit_cell: bool = True):
        self.requested_structures.append((material_id, conventional_unit_cell))
        return FakeStructure(material_id)


class FailingMPProvider(StructureProvider):
    name = "failing_mp"

    def can_resolve(self, structure_input: str) -> bool:
        return True

    def resolve(self, structure_input: str, work_dir: str, *, query: str = "", config=None):
        raise AssertionError("MP provider should not be called for local file inputs")


class MaterialsProjectProviderTests(unittest.TestCase):
    def test_resolving_by_material_id_writes_cif_artifact(self) -> None:
        fake_client = FakeMPClient(
            docs_by_material_id={
                "mp-149": [
                    {
                        "material_id": "mp-149",
                        "formula_pretty": "Si",
                        "symmetry": {"symbol": "Fd-3m"},
                        "energy_above_hull": 0.0,
                        "is_stable": True,
                        "theoretical": False,
                        "deprecated": False,
                    }
                ]
            }
        )
        provider = MaterialsProjectProvider(api_key="test-key", client_factory=lambda api_key: fake_client)

        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = provider.resolve("mp-149", tmpdir, query="run scf")
            self.assertEqual(resolved.source.provider, "materials_project")
            self.assertEqual(resolved.source.raw_input, "mp-149")
            self.assertEqual(resolved.structure_id, "mp-149")
            self.assertEqual(resolved.formula, "Si")
            self.assertEqual(resolved.lattice_type, "conventional")
            self.assertEqual(fake_client.requested_structures, [("mp-149", True)])
            cif_path = artifact_path(resolved, ArtifactType.CIF)
            self.assertIsNotNone(cif_path)
            self.assertIn("/materials_project/mp-149.cif", cif_path)
            self.assertEqual(Path(cif_path).read_text(encoding="utf-8"), "# CIF for mp-149\n")

    def test_resolving_by_formula_selects_rule_ranked_candidate(self) -> None:
        fake_client = FakeMPClient(
            docs_by_formula={
                "Si": [
                    {
                        "material_id": "mp-old",
                        "formula_pretty": "Si",
                        "symmetry": {"symbol": "P1"},
                        "energy_above_hull": 0.0,
                        "is_stable": True,
                        "theoretical": False,
                        "deprecated": True,
                    },
                    {
                        "material_id": "mp-149",
                        "formula_pretty": "Si",
                        "symmetry": {"symbol": "Fd-3m"},
                        "energy_above_hull": 0.0,
                        "is_stable": True,
                        "theoretical": False,
                        "deprecated": False,
                    },
                    {
                        "material_id": "mp-high",
                        "formula_pretty": "Si",
                        "symmetry": {"symbol": "P2"},
                        "energy_above_hull": 0.2,
                        "is_stable": False,
                        "theoretical": True,
                        "deprecated": False,
                    },
                ]
            }
        )
        provider = MaterialsProjectProvider(api_key="test-key", client_factory=lambda api_key: fake_client)
        resolver = StructureResolver(providers=[provider])

        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = resolver.resolve("Si", tmpdir, query="bands")

        self.assertEqual(resolved.structure_id, "mp-149")
        self.assertEqual(resolved.formula, "Si")
        self.assertEqual(resolved.candidates[0]["material_id"], "mp-149")
        self.assertTrue(resolved.candidates[0]["formula_match"])
        self.assertIn("Materials Project search for 'Si' returned 3 matches", resolved.metadata["notices"][0])

    def test_no_materials_project_entries_reports_input(self) -> None:
        fake_client = FakeMPClient(docs_by_material_id={"mp-404": []})
        provider = MaterialsProjectProvider(api_key="test-key", client_factory=lambda api_key: fake_client)
        resolver = StructureResolver(providers=[provider])

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(StructureResolutionError) as ctx:
                resolver.resolve("mp-404", tmpdir)

        message = str(ctx.exception)
        self.assertIn("Failed to resolve structure 'mp-404'", message)
        self.assertIn("No Materials Project entries found for 'mp-404'", message)

    def test_empty_input_error_mentions_local_providers(self) -> None:
        resolver = StructureResolver(providers=[])

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(StructureResolutionError) as ctx:
                resolver.resolve("", tmpdir)

        self.assertIn("Structure input is required", str(ctx.exception))
        self.assertIn("local .cif files and local ABACUS STRU/.stru files", str(ctx.exception))

    def test_unclaimed_input_reports_available_providers(self) -> None:
        resolver = StructureResolver(providers=[])

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(StructureResolutionError) as ctx:
                resolver.resolve("not/a/file.cif", tmpdir)

        self.assertIn("Unsupported local structure file 'not/a/file.cif'", str(ctx.exception))
        self.assertIn(".cif and ABACUS STRU/.stru", str(ctx.exception))


class LocalStructureProviderTests(unittest.TestCase):
    def test_local_cif_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cif_path = root / "local_si.cif"
            cif_path.write_text("# intentionally minimal CIF fixture\n", encoding="utf-8")

            resolved = StructureResolver().resolve(str(cif_path), str(root), query="run scf")

            self.assertEqual(resolved.source.provider, "local_cif")
            self.assertEqual(resolved.source.raw_input, str(cif_path))
            self.assertEqual(resolved.structure_id, "local_si")
            self.assertEqual(resolved.formula, "local_si")
            self.assertEqual(resolved.lattice_type, "input")
            self.assertEqual(artifact_path(resolved, ArtifactType.CIF), str(cif_path.resolve()))

    def test_local_stru_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stru_path = root / "STRU"
            stru_path.write_text(STRU_TEXT, encoding="utf-8")

            resolved = StructureResolver().resolve(str(stru_path), str(root), query="run scf")

            self.assertEqual(resolved.source.provider, "local_stru")
            self.assertEqual(resolved.structure_id, "STRU")
            self.assertEqual(resolved.formula, "Si")
            self.assertEqual(resolved.metadata["species"], ["Si"])
            self.assertEqual(artifact_path(resolved, ArtifactType.STRU), str(stru_path.resolve()))

    def test_local_files_take_precedence_over_mp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cif_path = root / "Si.cif"
            cif_path.write_text("# local CIF wins\n", encoding="utf-8")
            resolver = StructureResolver(providers=[LocalCIFProvider(), LocalSTRUProvider(), FailingMPProvider()])

            resolved = resolver.resolve(str(cif_path), str(root))

            self.assertEqual(resolved.source.provider, "local_cif")
            self.assertEqual(artifact_path(resolved, ArtifactType.CIF), str(cif_path.resolve()))

    def test_missing_local_cif_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.cif"

            with self.assertRaises(StructureResolutionError) as ctx:
                StructureResolver().resolve(str(missing), tmpdir)

        message = str(ctx.exception)
        self.assertIn("Failed to resolve structure", message)
        self.assertIn("Local CIF file not found", message)
        self.assertIn("missing.cif", message)

    def test_missing_local_stru_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.stru"

            with self.assertRaises(StructureResolutionError) as ctx:
                StructureResolver().resolve(str(missing), tmpdir)

        message = str(ctx.exception)
        self.assertIn("Failed to resolve structure", message)
        self.assertIn("Local ABACUS STRU file not found", message)

    def test_unsupported_local_file_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xyz_path = Path(tmpdir) / "structure.xyz"
            xyz_path.write_text("not supported\n", encoding="utf-8")

            with self.assertRaises(StructureResolutionError) as ctx:
                StructureResolver().resolve(str(xyz_path), tmpdir)

        message = str(ctx.exception)
        self.assertIn("Unsupported local structure file", message)
        self.assertIn("Supported local formats are .cif and ABACUS STRU/.stru", message)


if __name__ == "__main__":
    unittest.main()
