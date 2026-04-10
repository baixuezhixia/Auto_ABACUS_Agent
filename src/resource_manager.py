# 资源管理器，
#根据元素名去 Pseudopotential 和 StandardOrbitals 里找对应文件

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional


def resolve_pseudo_map(species: Iterable[str], pseudo_dir: str) -> Dict[str, str]:
    base = Path(pseudo_dir).expanduser().resolve()
    mapping: Dict[str, str] = {}
    for element in species:
        candidate = _find_by_prefix(base, element, suffixes=(".upf", ".UPF"))
        if candidate is None:
            raise FileNotFoundError(f"No pseudopotential found for {element} under {base}")
        mapping[element] = str(candidate)
    return mapping


def resolve_orbital_map(species: Iterable[str], orb_dir: str) -> Dict[str, str]:
    base = Path(orb_dir).expanduser().resolve()
    mapping: Dict[str, str] = {}
    for element in species:
        candidate = _find_by_prefix(base, element, suffixes=(".orb", ".ORB"))
        if candidate is None:
            raise FileNotFoundError(f"No orbital file found for {element} under {base}")
        mapping[element] = str(candidate)
    return mapping


def list_species_files(base_dir: str, suffix: str) -> List[str]:
    base = Path(base_dir).expanduser().resolve()
    if not base.exists():
        return []
    return [str(path) for path in sorted(base.glob(f"*{suffix}"))]


def _find_by_prefix(base: Path, element: str, suffixes: tuple[str, ...]) -> Optional[Path]:
    for suffix in suffixes:
        exact = base / f"{element}{suffix}"
        if exact.exists():
            return exact
    candidates = sorted(p for p in base.iterdir() if p.is_file() and p.name.startswith(f"{element}_"))
    for candidate in candidates:
        if candidate.suffix.lower() in {s.lower() for s in suffixes}:
            return candidate
    return None
