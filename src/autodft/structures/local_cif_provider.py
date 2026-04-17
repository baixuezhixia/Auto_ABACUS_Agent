"""Local CIF structure provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from autodft.core.enums import ArtifactType
from autodft.core.exceptions import StructureResolutionError
from autodft.core.models import ResolvedStructure
from autodft.structures.base import StructureProvider
from autodft.structures.structure_object import make_artifact, make_resolved_structure


class LocalCIFProvider(StructureProvider):
    """Resolve an existing local ``.cif`` file into a structure artifact."""

    name = "local_cif"

    def can_resolve(self, structure_input: str) -> bool:
        """Return whether the input is a CIF-like local file path."""

        return is_cif_path(structure_input)

    def resolve(
        self,
        structure_input: str,
        work_dir: str,
        *,
        query: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> ResolvedStructure:
        """Return a ``ResolvedStructure`` with the CIF file as its artifact."""

        _ = work_dir, config
        path = Path(structure_input).expanduser()
        if not path.exists():
            raise StructureResolutionError(f"Local CIF file not found: {path}")
        if not path.is_file():
            raise StructureResolutionError(f"Local CIF input is not a file: {path}")

        resolved = path.resolve()
        formula = _formula_from_cif(resolved) or resolved.stem
        return make_resolved_structure(
            provider=self.name,
            raw_input=structure_input,
            query=query,
            structure_id=resolved.stem,
            formula=formula,
            artifacts=[
                make_artifact(
                    ArtifactType.CIF,
                    resolved,
                    label="local_cif",
                    metadata={"source": self.name},
                )
            ],
            lattice_type="input",
            metadata={"path": str(resolved)},
        )


def is_cif_path(value: str) -> bool:
    """Return whether a value should be treated as a CIF path."""

    return Path(value.strip()).suffix.lower() == ".cif"


def _formula_from_cif(path: Path) -> Optional[str]:
    """Best-effort formula extraction without making pymatgen mandatory."""

    try:
        from pymatgen.core import Structure

        return Structure.from_file(str(path)).composition.reduced_formula
    except Exception:
        return None


__all__ = ["LocalCIFProvider", "is_cif_path"]

