"""ABACUS STRU reading, rendering, and CIF conversion."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from autodft.abacus.resources import AbacusResourceConfig, resolve_orbital_map, resolve_pseudo_map
from autodft.core.enums import BasisType
from autodft.core.exceptions import InputGenerationError


ANGSTROM_TO_BOHR = 1.8897261254578281
MOVABLE_ATOM_FLAGS = ("1", "1", "1")


def convert_cif_to_stru(
    cif_path: str | Path,
    output_path: str | Path,
    resources: AbacusResourceConfig,
    *,
    basis_type: BasisType = BasisType.PW,
) -> str:
    """Convert a CIF file to ABACUS STRU using configured resources."""

    try:
        from pymatgen.core import Element, Structure
    except ImportError as exc:
        raise InputGenerationError("pymatgen is required for CIF to STRU conversion.") from exc

    structure = Structure.from_file(str(cif_path))
    if not structure.is_ordered:
        raise InputGenerationError("CIF contains partial occupancies or disorder; cannot convert directly to ABACUS STRU.")

    species = _ordered_species_from_pymatgen(structure)
    pseudo_map = resolve_pseudo_map(species, resources.pseudo_dir)
    include_orbitals = basis_type == BasisType.LCAO
    orb_map = resolve_orbital_map(species, resources.orb_dir) if include_orbitals else {}

    lines: List[str] = ["ATOMIC_SPECIES"]
    for symbol in species:
        mass = float(Element(symbol).atomic_mass)
        pp_name = Path(pseudo_map[symbol]).name
        lines.append(f"{symbol} {mass:.6f} {pp_name} upf201")

    if include_orbitals and orb_map:
        lines.extend(["", "NUMERICAL_ORBITAL"])
        for symbol in species:
            lines.append(Path(orb_map[symbol]).name)

    lines.extend(["", "LATTICE_CONSTANT", f"{ANGSTROM_TO_BOHR:.15f}", "", "LATTICE_VECTORS"])
    for vector in structure.lattice.matrix:
        lines.append(" ".join(f"{value:.12f}" for value in vector))

    lines.extend(["", "ATOMIC_POSITIONS", "Direct"])
    grouped_sites = _group_fractional_sites(structure, species)
    for symbol in species:
        lines.append(symbol)
        lines.append("0.0")
        coords = grouped_sites[symbol]
        lines.append(str(len(coords)))
        for frac in coords:
            lines.append(" ".join(f"{value:.9f}" for value in frac) + " 0 0 0")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(output.resolve())


def extract_species(structure_text: str) -> List[str]:
    """Extract species names from an ABACUS STRU ``ATOMIC_SPECIES`` block."""

    species: List[str] = []
    in_species = False
    for raw_line in structure_text.splitlines():
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
    if not species:
        raise InputGenerationError("No ATOMIC_SPECIES block found in structure file")
    return species


def render_stru_with_resources(
    structure_text: str,
    species: Iterable[str],
    pseudo_map: Dict[str, str],
    orb_map: Dict[str, str] | None = None,
    *,
    include_numerical_orbital: bool = False,
    atom_coordinate_flags: Optional[Tuple[str, str, str]] = None,
) -> str:
    """Render STRU text with resource filenames normalized for ABACUS."""

    orb_map = dict(orb_map or {})
    lines = structure_text.splitlines()
    output: List[str] = []
    in_species = False
    skip_orbital_block = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.upper().startswith("ATOMIC_SPECIES"):
            in_species = True
            output.append(line)
            continue
        if stripped.upper().startswith("NUMERICAL_ORBITAL") and not include_numerical_orbital:
            skip_orbital_block = True
            continue
        if skip_orbital_block:
            if not stripped or stripped.upper().startswith(("LATTICE", "ATOMIC_POSITIONS", "CELL_PARAMETERS", "K_POINTS")):
                skip_orbital_block = False
                output.append(line if stripped else "")
            continue
        if in_species:
            if not stripped or stripped.upper().startswith(("LATTICE", "ATOMIC_POSITIONS", "CELL_PARAMETERS", "K_POINTS", "NUMERICAL_ORBITAL")):
                in_species = False
                output.append(line if stripped else "")
                continue
            parts = stripped.split()
            if len(parts) >= 2 and parts[0] in pseudo_map:
                pp_name = Path(pseudo_map[parts[0]]).name
                output.append(f"{parts[0]} {parts[1]} {pp_name} upf201")
                continue
        output.append(line)

    if include_numerical_orbital and orb_map:
        output.append("")
        output.append("NUMERICAL_ORBITAL")
        for element in species:
            output.append(Path(orb_map[element]).name)

    rendered = "\n".join(output).rstrip() + "\n"
    if atom_coordinate_flags is not None:
        rendered = set_atomic_position_flags(rendered, atom_coordinate_flags)
    return rendered


def set_atomic_position_flags(structure_text: str, flags: Tuple[str, str, str]) -> str:
    """Set ABACUS coordinate move flags inside the ``ATOMIC_POSITIONS`` block."""

    output: List[str] = []
    in_positions = False
    for raw_line in structure_text.splitlines():
        stripped = raw_line.strip()
        upper = stripped.upper()
        if upper.startswith("ATOMIC_POSITIONS"):
            in_positions = True
            output.append(raw_line)
            continue
        if in_positions and upper.startswith(("ATOMIC_SPECIES", "LATTICE", "CELL_PARAMETERS", "K_POINTS", "NUMERICAL_ORBITAL")):
            in_positions = False

        output.append(_set_coordinate_line_flags(raw_line, flags) if in_positions else raw_line)
    return "\n".join(output).rstrip() + "\n"


def _set_coordinate_line_flags(line: str, flags: Tuple[str, str, str]) -> str:
    stripped = line.strip()
    if not stripped:
        return line
    parts = stripped.split()
    if len(parts) < 3 or not _looks_like_coordinate(parts[:3]):
        return line

    rest = parts[6:] if len(parts) >= 6 and _looks_like_move_flags(parts[3:6]) else parts[3:]
    indent = line[: len(line) - len(line.lstrip())]
    return indent + " ".join(parts[:3] + list(flags) + rest)


def _looks_like_coordinate(parts: List[str]) -> bool:
    try:
        for item in parts:
            float(item)
    except ValueError:
        return False
    return True


def _looks_like_move_flags(parts: List[str]) -> bool:
    return len(parts) == 3 and all(item in {"0", "1"} for item in parts)


def _ordered_species_from_pymatgen(structure) -> List[str]:
    seen: Dict[str, None] = OrderedDict()
    for site in structure.sites:
        seen.setdefault(site.specie.symbol, None)
    return list(seen.keys())


def _group_fractional_sites(structure, species: List[str]) -> Dict[str, List[List[float]]]:
    grouped: Dict[str, List[List[float]]] = {symbol: [] for symbol in species}
    for site in structure.sites:
        grouped[site.specie.symbol].append([float(x) for x in site.frac_coords])
    return grouped


__all__ = [
    "ANGSTROM_TO_BOHR",
    "MOVABLE_ATOM_FLAGS",
    "convert_cif_to_stru",
    "extract_species",
    "render_stru_with_resources",
    "set_atomic_position_flags",
]
