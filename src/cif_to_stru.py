from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

from pymatgen.core import Element, Structure

from resource_manager import resolve_orbital_map, resolve_pseudo_map

ANGSTROM_TO_BOHR = 1.8897261254578281


def convert_cif_to_stru(
    cif_path: str,
    output_path: str,
    pseudo_dir: str,
    orb_dir: str = "",
    include_numerical_orbital: bool = False,
) -> str:
    structure = Structure.from_file(cif_path)
    _ensure_ordered_structure(structure)

    species = _ordered_species(structure)
    pseudo_map = resolve_pseudo_map(species, pseudo_dir)
    orb_map = resolve_orbital_map(species, orb_dir) if include_numerical_orbital and orb_dir else {}

    content = _render_stru(structure, species, pseudo_map, orb_map, include_numerical_orbital)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.resolve())


def _ensure_ordered_structure(structure: Structure) -> None:
    if not structure.is_ordered:
        raise ValueError("CIF contains partial occupancies or disorder; cannot convert directly to ABACUS STRU.")


def _ordered_species(structure: Structure) -> List[str]:
    seen: Dict[str, None] = OrderedDict()
    for site in structure.sites:
        symbol = site.specie.symbol
        seen.setdefault(symbol, None)
    return list(seen.keys())


def _render_stru(
    structure: Structure,
    species: List[str],
    pseudo_map: Dict[str, str],
    orb_map: Dict[str, str],
    include_numerical_orbital: bool,
) -> str:
    lines: List[str] = ["ATOMIC_SPECIES"]
    for symbol in species:
        mass = float(Element(symbol).atomic_mass)
        pp_name = Path(pseudo_map[symbol]).name
        lines.append(f"{symbol} {mass:.6f} {pp_name} upf201")

    if include_numerical_orbital and orb_map:
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

    return "\n".join(lines) + "\n"


def _group_fractional_sites(structure: Structure, species: List[str]) -> Dict[str, List[List[float]]]:
    grouped: Dict[str, List[List[float]]] = {symbol: [] for symbol in species}
    for site in structure.sites:
        grouped[site.specie.symbol].append([float(x) for x in site.frac_coords])
    return grouped
