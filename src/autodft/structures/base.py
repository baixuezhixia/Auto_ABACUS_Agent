"""Provider interface for structure resolution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from autodft.core.models import ResolvedStructure


class StructureProvider(ABC):
    """Base class for concrete structure providers.

    A provider turns a user-facing structure input into a ``ResolvedStructure``.
    Phase 2 adds local CIF and ABACUS STRU providers ahead of the Materials
    Project provider so file inputs can be resolved before remote lookup.
    """

    name: str = "structure_provider"

    @abstractmethod
    def can_resolve(self, structure_input: str) -> bool:
        """Return whether this provider can attempt the input."""

    @abstractmethod
    def resolve(
        self,
        structure_input: str,
        work_dir: str,
        *,
        query: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> ResolvedStructure:
        """Resolve the input into concrete structure artifacts."""


__all__ = ["StructureProvider"]
