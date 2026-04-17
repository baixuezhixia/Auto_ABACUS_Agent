"""Structure providers, selectors, converters, and structure artifacts."""

from autodft.structures.base import StructureProvider
from autodft.structures.local_cif_provider import LocalCIFProvider, is_cif_path
from autodft.structures.local_stru_provider import LocalSTRUProvider, is_stru_path
from autodft.structures.mp_provider import MaterialsProjectProvider, is_material_id, select_materials_project_doc
from autodft.structures.resolver import StructureResolver, resolve_structure
from autodft.structures.structure_object import (
    StructureCandidate,
    artifact_path,
    make_artifact,
    make_resolved_structure,
)

__all__ = [
    "LocalCIFProvider",
    "LocalSTRUProvider",
    "MaterialsProjectProvider",
    "StructureCandidate",
    "StructureProvider",
    "StructureResolver",
    "artifact_path",
    "is_cif_path",
    "is_material_id",
    "is_stru_path",
    "make_artifact",
    "make_resolved_structure",
    "resolve_structure",
    "select_materials_project_doc",
]
