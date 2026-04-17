"""Local ABACUS STRU structure provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from autodft.core.enums import ArtifactType
from autodft.core.exceptions import StructureResolutionError
from autodft.core.models import ResolvedStructure
from autodft.structures.base import StructureProvider
from autodft.structures.structure_object import make_artifact, make_resolved_structure


class LocalSTRUProvider(StructureProvider):
    """Resolve an existing local ABACUS ``STRU`` file into a structure artifact."""

    name = "local_stru"

    def can_resolve(self, structure_input: str) -> bool:
        """Return whether the input is an ABACUS STRU-like path."""

        return is_stru_path(structure_input)

    def resolve(
        self,
        structure_input: str,
        work_dir: str,
        *,
        query: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> ResolvedStructure:
        """Return a ``ResolvedStructure`` with the STRU file as its artifact."""

        _ = work_dir, config
        path = Path(structure_input).expanduser()
        if not path.exists():
            raise StructureResolutionError(f"Local ABACUS STRU file not found: {path}")
        if not path.is_file():
            raise StructureResolutionError(f"Local ABACUS STRU input is not a file: {path}")

        resolved = path.resolve()
        species = _extract_species(resolved)
        formula = "".join(species) if species else resolved.stem
        return make_resolved_structure(
            provider=self.name,
            raw_input=structure_input,
            query=query,
            structure_id=resolved.stem if resolved.stem else "STRU",
            formula=formula,
            artifacts=[
                make_artifact(
                    ArtifactType.STRU,
                    resolved,
                    label="local_stru",
                    metadata={"source": self.name},
                )
            ],
            lattice_type="input",
            metadata={"path": str(resolved), "species": species},
        )


def is_stru_path(value: str) -> bool:
    """Return whether a value should be treated as an ABACUS STRU path."""

    path = Path(value.strip())
    return path.name.upper() == "STRU" or path.suffix.lower() == ".stru"


def _extract_species(path: Path) -> List[str]:
    """Extract species from a STRU ``ATOMIC_SPECIES`` block when present."""

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    species: List[str] = []
    in_species = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("ATOMIC_SPECIES"):
            in_species = True
            continue
        if in_species:
            if line.upper().startswith(("LATTICE", "ATOMIC_POSITIONS", "CELL_PARAMETERS", "K_POINTS", "NUMERICAL_ORBITAL")):
                break
            parts = line.split()
            if parts:
                species.append(parts[0])
    return species


__all__ = ["LocalSTRUProvider", "is_stru_path"]

