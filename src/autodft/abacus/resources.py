"""Pseudopotential and numerical orbital resource resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from autodft.core.exceptions import InputGenerationError


@dataclass
class AbacusResourceConfig:
    """Filesystem locations for ABACUS pseudopotential and orbital files."""

    pseudo_dir: str
    orb_dir: str = ""

    def resolved_pseudo_dir(self) -> Path:
        """Return the configured pseudopotential directory as an absolute path."""

        return Path(self.pseudo_dir).expanduser().resolve()

    def resolved_orb_dir(self) -> Path:
        """Return the configured numerical orbital directory as an absolute path."""

        return Path(self.orb_dir).expanduser().resolve()


def resolve_pseudo_map(species: Iterable[str], pseudo_dir: str) -> Dict[str, str]:
    """Resolve one pseudopotential file for each element symbol."""

    base = Path(pseudo_dir).expanduser().resolve()
    mapping: Dict[str, str] = {}
    for element in species:
        candidate = _find_by_prefix(base, element, suffixes=(".upf", ".UPF"))
        if candidate is None:
            raise InputGenerationError(f"No pseudopotential found for {element} under {base}")
        mapping[element] = str(candidate)
    return mapping


def resolve_orbital_map(species: Iterable[str], orb_dir: str) -> Dict[str, str]:
    """Resolve one numerical orbital file for each element symbol."""

    base = Path(orb_dir).expanduser().resolve()
    mapping: Dict[str, str] = {}
    for element in species:
        candidate = _find_by_prefix(base, element, suffixes=(".orb", ".ORB"))
        if candidate is None:
            raise InputGenerationError(f"No orbital file found for {element} under {base}")
        mapping[element] = str(candidate)
    return mapping


def list_species_files(base_dir: str, suffix: str) -> List[str]:
    """List resource files matching a suffix under a directory."""

    base = Path(base_dir).expanduser().resolve()
    if not base.exists():
        return []
    return [str(path) for path in sorted(base.glob(f"*{suffix}"))]


def _find_by_prefix(base: Path, element: str, suffixes: tuple[str, ...]) -> Optional[Path]:
    if not base.is_dir():
        return None

    for suffix in suffixes:
        exact = base / f"{element}{suffix}"
        if exact.exists():
            return exact

    suffix_set = {suffix.lower() for suffix in suffixes}
    candidates = sorted(path for path in base.iterdir() if path.is_file() and path.name.startswith(f"{element}_"))
    for candidate in candidates:
        if candidate.suffix.lower() in suffix_set:
            return candidate
    return None


__all__ = [
    "AbacusResourceConfig",
    "list_species_files",
    "resolve_orbital_map",
    "resolve_pseudo_map",
]

