"""Provider-agnostic structure resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from autodft.core.exceptions import AutoDFTError, StructureResolutionError
from autodft.core.models import ResolvedStructure
from autodft.structures.base import StructureProvider
from autodft.structures.local_cif_provider import LocalCIFProvider
from autodft.structures.local_stru_provider import LocalSTRUProvider
from autodft.structures.mp_provider import MaterialsProjectProvider


class StructureResolver:
    """Resolve structure inputs through an ordered list of providers.

    The default resolver checks local CIF and local ABACUS STRU files before
    falling back to Materials Project formula/material-id resolution.
    """

    def __init__(self, providers: Optional[Iterable[StructureProvider]] = None) -> None:
        self.providers = list(providers) if providers is not None else [
            LocalCIFProvider(),
            LocalSTRUProvider(),
            MaterialsProjectProvider(),
        ]

    def resolve(
        self,
        structure_input: str,
        work_dir: str,
        *,
        query: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> ResolvedStructure:
        """Resolve a user structure input using the first matching provider."""

        raw_input = structure_input.strip()
        if not raw_input:
            raise StructureResolutionError(
                "Structure input is required. Expected a Materials Project material ID or formula; "
                "local .cif files and local ABACUS STRU/.stru files are also supported."
            )

        failures: List[str] = []
        matched_provider = False
        for provider in self.providers:
            if not provider.can_resolve(raw_input):
                continue
            matched_provider = True
            try:
                return provider.resolve(raw_input, work_dir, query=query, config=config or {})
            except AutoDFTError as exc:
                failures.append(f"{provider.name}: {exc}")

        if failures:
            raise StructureResolutionError(
                f"Failed to resolve structure '{raw_input}'. " + " | ".join(failures)
            )
        if _looks_like_local_file_input(raw_input):
            raise StructureResolutionError(
                f"Unsupported local structure file '{raw_input}'. "
                "Supported local formats are .cif and ABACUS STRU/.stru files."
            )
        if not matched_provider:
            provider_names = ", ".join(provider.name for provider in self.providers) or "none"
            raise StructureResolutionError(
                f"No structure provider could resolve '{raw_input}'. Available providers: {provider_names}. "
                "Use a Materials Project material ID/formula, a local .cif file, or a local ABACUS STRU/.stru file."
            )
        raise StructureResolutionError(f"Failed to resolve structure '{raw_input}'.")


def resolve_structure(
    structure_input: str,
    work_dir: str,
    *,
    query: str = "",
    config: Optional[Dict[str, Any]] = None,
    providers: Optional[Iterable[StructureProvider]] = None,
) -> ResolvedStructure:
    """Convenience wrapper around ``StructureResolver``."""

    return StructureResolver(providers=providers).resolve(
        structure_input,
        work_dir,
        query=query,
        config=config,
    )


def _looks_like_local_file_input(value: str) -> bool:
    path = Path(value).expanduser()
    if path.is_absolute() or value.startswith(("./", "../", "~")):
        return True
    if "/" in value or "\\" in value:
        return True
    return bool(path.suffix)


__all__ = ["StructureResolver", "resolve_structure"]
