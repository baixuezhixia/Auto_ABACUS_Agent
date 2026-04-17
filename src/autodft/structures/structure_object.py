"""Helpers for building structure resolution domain objects.

This module keeps provider-specific code from hand-assembling core model
objects in several places. Future local CIF and STRU providers should also use
these helpers when creating ``ResolvedStructure`` values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from autodft.core.enums import ArtifactType
from autodft.core.models import ArtifactRef, ResolvedStructure, StructureSource


@dataclass
class StructureCandidate:
    """Small normalized view of a provider search candidate."""

    structure_id: str
    formula: str
    spacegroup: str = ""
    energy_above_hull: Optional[float] = None
    is_stable: bool = False
    theoretical: bool = False
    deprecated: bool = False
    formula_match: bool = False
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return the candidate shape used by reports and selection metadata."""

        payload = {
            "material_id": self.structure_id,
            "formula": self.formula,
            "spacegroup": self.spacegroup,
            "energy_above_hull": self.energy_above_hull,
            "is_stable": self.is_stable,
            "theoretical": self.theoretical,
            "deprecated": self.deprecated,
            "formula_match": self.formula_match,
        }
        if self.metadata:
            payload.update(self.metadata)
        return payload


def make_artifact(
    artifact_type: ArtifactType,
    path: Path | str,
    *,
    label: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> ArtifactRef:
    """Create an artifact reference with a normalized string path."""

    return ArtifactRef(
        artifact_type=artifact_type,
        path=str(Path(path).resolve()),
        label=label,
        metadata=dict(metadata or {}),
    )


def make_resolved_structure(
    *,
    provider: str,
    raw_input: str,
    query: str,
    structure_id: str,
    formula: str,
    artifacts: Iterable[ArtifactRef],
    lattice_type: str = "conventional",
    candidates: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ResolvedStructure:
    """Create the shared resolved-structure model for a provider result."""

    source = StructureSource(
        provider=provider,
        raw_input=raw_input,
        query=query,
        source_id=structure_id,
    )
    return ResolvedStructure(
        source=source,
        structure_id=structure_id,
        formula=formula,
        lattice_type=lattice_type,
        artifacts=list(artifacts),
        candidates=list(candidates or []),
        metadata=dict(metadata or {}),
    )


def artifact_path(structure: ResolvedStructure, artifact_type: ArtifactType) -> Optional[str]:
    """Return the first artifact path matching ``artifact_type``."""

    for artifact in structure.artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact.path
    return None


__all__ = [
    "StructureCandidate",
    "artifact_path",
    "make_artifact",
    "make_resolved_structure",
]
