"""ABACUS INPUT, KPT, and STRU file generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from autodft.abacus.presets import AbacusInputPreset, calculation_for_task, default_ks_solver_for_basis, is_followup_task
from autodft.abacus.resources import AbacusResourceConfig, resolve_orbital_map, resolve_pseudo_map
from autodft.abacus.structure_io import MOVABLE_ATOM_FLAGS, extract_species, render_stru_with_resources
from autodft.core.enums import ArtifactType, BasisType, TaskType
from autodft.core.exceptions import InputGenerationError
from autodft.core.models import ArtifactRef, TaskNode


CHARGE_HANDOFF_PATTERNS = ("*-CHARGE-DENSITY.restart", "chg.cube", "chg1.cube", "chg2.cube")
OPTIONAL_HANDOFF_FILES = ("onsite.dm",)


@dataclass
class AbacusInputSet:
    """Paths for generated ABACUS task input files."""

    input_path: Path
    stru_path: Path
    kpt_path: Path

    def artifacts(self, task_id: str) -> list[ArtifactRef]:
        """Return generated files as shared artifact references."""

        return [
            ArtifactRef(ArtifactType.INPUT, str(self.input_path), task_id=task_id),
            ArtifactRef(ArtifactType.STRU, str(self.stru_path), task_id=task_id),
            ArtifactRef(ArtifactType.KPT, str(self.kpt_path), task_id=task_id),
        ]


def generate_abacus_inputs(
    task: TaskNode,
    task_dir: str | Path,
    structure_path: str | Path,
    *,
    preset: Optional[AbacusInputPreset] = None,
    resources: Optional[AbacusResourceConfig] = None,
    dependency_task_dir: str | Path | None = None,
    dependency_task_id: Optional[str] = None,
) -> AbacusInputSet:
    """Generate ABACUS ``INPUT``, ``STRU``, and ``KPT`` files for a task."""

    preset = preset or AbacusInputPreset()
    if resources is None:
        raise InputGenerationError("ABACUS resources must be provided for input generation.")

    task_dir = Path(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)
    structure_path = Path(structure_path)

    structure_text = structure_path.read_text(encoding="utf-8")
    species = extract_species(structure_text)
    basis_type = resolve_basis_type(task, preset, resources)
    include_orbitals = basis_type == BasisType.LCAO
    pseudo_map = resolve_pseudo_map(species, resources.pseudo_dir)
    orb_map = resolve_orbital_map(species, resources.orb_dir) if include_orbitals else {}

    read_file_dir = None
    if dependency_task_dir is not None and dependency_task_id and uses_scf_handoff(task.task_type):
        read_file_dir = prepare_read_file_dir(
            task_id=task.task_id,
            source_out_dir=Path(dependency_task_dir) / f"OUT.{dependency_task_id}",
            task_dir=task_dir,
        )

    input_content = render_input_content(
        task=task,
        preset=preset,
        resources=resources,
        basis_type=basis_type,
        structure_text=structure_text,
        read_file_dir=read_file_dir,
    )
    kpt_content = render_kpt_content(task.task_type, preset)
    stru_content = render_stru_with_resources(
        structure_text,
        species,
        pseudo_map,
        orb_map,
        include_numerical_orbital=include_orbitals,
        atom_coordinate_flags=atom_coordinate_flags_for_task(task.task_type),
    )

    input_path = task_dir / "INPUT"
    stru_path = task_dir / "STRU"
    kpt_path = task_dir / "KPT"
    input_path.write_text(input_content, encoding="utf-8")
    stru_path.write_text(stru_content, encoding="utf-8")
    kpt_path.write_text(kpt_content, encoding="utf-8")
    return AbacusInputSet(input_path=input_path, stru_path=stru_path, kpt_path=kpt_path)


def resolve_basis_type(task: TaskNode, preset: AbacusInputPreset, resources: AbacusResourceConfig) -> BasisType:
    """Resolve basis type from task params, task field, or preset."""

    raw_basis_type = task.params.get("basis_type") or (task.basis_type.value if task.basis_type else None) or preset.basis_type.value
    basis_value = str(raw_basis_type).strip().lower()
    if basis_value not in {item.value for item in BasisType}:
        raise InputGenerationError(f"Unsupported basis_type '{raw_basis_type}'. Expected one of: pw, lcao")
    basis_type = BasisType(basis_value)
    if basis_type == BasisType.LCAO and not resources.orb_dir:
        raise InputGenerationError("basis_type 'lcao' requires abacus.orb_dir or abacus.orbital_dir to be configured")
    return basis_type


def resolve_ks_solver(basis_type: BasisType, preset: AbacusInputPreset) -> str:
    """Resolve the solver from explicit config or the basis-specific default."""

    if preset.ks_solver:
        return str(preset.ks_solver)
    return default_ks_solver_for_basis(basis_type)


def resolve_orbital_dir_for_input(basis_type: BasisType, resources: AbacusResourceConfig) -> Optional[str]:
    """Return the ABACUS orbital directory line value for LCAO inputs."""

    if basis_type != BasisType.LCAO:
        return None
    return str(resources.resolved_orb_dir())


def atom_coordinate_flags_for_task(task_type: TaskType) -> Optional[tuple[str, str, str]]:
    """Return task-specific default coordinate flags for generated STRU files."""

    if task_type == TaskType.RELAX:
        return MOVABLE_ATOM_FLAGS
    return None


def render_input_content(
    *,
    task: TaskNode,
    preset: AbacusInputPreset,
    resources: AbacusResourceConfig,
    basis_type: BasisType,
    structure_text: str,
    read_file_dir: Optional[str] = None,
) -> str:
    """Render ABACUS ``INPUT`` content for a task."""

    symmetry = 0 if task.task_type == TaskType.BANDS else preset.symmetry
    ks_solver = resolve_ks_solver(basis_type, preset)
    ecutrho = resolve_ecutrho_for_input(preset)
    orbital_dir = resolve_orbital_dir_for_input(basis_type, resources)
    out_stru = resolve_out_stru_for_task(task.task_type, preset)
    lines = [
        "INPUT_PARAMETERS",
        f"suffix {task.task_id}",
        "stru_file STRU",
        "kpoint_file KPT",
        f"pseudo_dir {resources.pseudo_dir}",
        f"basis_type {basis_type.value}",
        f"calculation {calculation_for_task(task.task_type, task.params)}",
        f"ecutwfc {preset.ecutwfc:g}",
        f"scf_thr {preset.scf_thr}",
        f"scf_nmax {preset.scf_nmax}",
        f"ks_solver {ks_solver}",
        f"nspin {preset.nspin}",
        f"symmetry {symmetry}",
        f"out_level {preset.out_level}",
        f"out_stru {out_stru}",
    ]
    if ecutrho is not None:
        lines.insert(8, f"ecutrho {ecutrho:g}")
    if orbital_dir is not None:
        lines.append(f"orbital_dir {orbital_dir}")
    if "LATTICE_VECTORS" not in structure_text.upper():
        lines.append(f"latname {preset.latname}")

    if task.task_type in {TaskType.SCF, TaskType.RELAX}:
        lines.append(f"smearing_method {preset.smearing_method}")
        if preset.smearing_method != "fixed":
            lines.append(f"smearing_sigma {preset.smearing_sigma}")
        lines.append(f"out_chg {out_chg_for_task(task.task_type)}")

    if task.task_type == TaskType.RELAX:
        lines.extend([
            f"force_thr_ev {preset.relax_force_thr}",
            "relax_method cg 1",
        ])

    if task.task_type == TaskType.ELASTIC:
        lines.extend([
            f"force_thr_ev {preset.relax_force_thr}",
            f"stress_thr {preset.stress_thr}",
            "relax_method cg 1",
        ])

    if is_followup_task(task.task_type):
        lines.append("init_chg file")
        if read_file_dir is not None:
            lines.append(f"read_file_dir {read_file_dir}")
        lines.append("out_chg 0")
        if task.task_type == TaskType.BANDS:
            lines.append("out_band 1")
        if task.task_type == TaskType.DOS:
            lines.extend([
                "out_dos 1",
                f"dos_emin_ev {preset.dos_emin_ev}",
                f"dos_emax_ev {preset.dos_emax_ev}",
                f"dos_edelta_ev {preset.dos_edelta_ev}",
            ])
    elif task.task_type == TaskType.ELASTIC and read_file_dir is not None:
        lines.append("init_chg file")
        lines.append(f"read_file_dir {read_file_dir}")

    return "\n".join(lines) + "\n"


def render_kpt_content(task_type: TaskType, preset: AbacusInputPreset) -> str:
    """Render ABACUS ``KPT`` content for a task."""

    if task_type == TaskType.BANDS:
        lines = ["K_POINTS", str(len(preset.kpath)), "Line_Cartesian"]
        for point in preset.kpath:
            lines.append(f"{point[0]} {point[1]} {point[2]} {point[3]}")
        return "\n".join(lines) + "\n"

    kmesh = preset.kmesh
    return f"""K_POINTS
0
Gamma
{kmesh[0]} {kmesh[1]} {kmesh[2]} 0 0 0
"""


def prepare_read_file_dir(task_id: str, source_out_dir: Path, task_dir: Path) -> Optional[str]:
    """Stage charge-density files from a dependency output directory."""

    if not source_out_dir.is_dir():
        return None

    staging_dir = task_dir / "READ_CHG"
    staging_dir.mkdir(parents=True, exist_ok=True)
    copied_charge = False

    restart_candidates = sorted(source_out_dir.glob("*-CHARGE-DENSITY.restart"))
    if restart_candidates:
        src = restart_candidates[0]
        dst = staging_dir / f"{task_id}-CHARGE-DENSITY.restart"
        dst.write_bytes(src.read_bytes())
        copied_charge = True

    for cube_name in ("chg.cube", "chg1.cube", "chg2.cube"):
        cube_path = source_out_dir / cube_name
        if cube_path.is_file():
            (staging_dir / cube_name).write_bytes(cube_path.read_bytes())
            copied_charge = True

    for filename in OPTIONAL_HANDOFF_FILES:
        optional_path = source_out_dir / filename
        if optional_path.is_file():
            (staging_dir / filename).write_bytes(optional_path.read_bytes())

    return "READ_CHG" if copied_charge else None


def has_charge_handoff_files(source_out_dir: Path) -> bool:
    """Return whether an SCF output directory contains reusable charge files."""

    if not source_out_dir.is_dir():
        return False
    return any(source_out_dir.glob("*-CHARGE-DENSITY.restart")) or any((source_out_dir / name).is_file() for name in ("chg.cube", "chg1.cube", "chg2.cube"))


def uses_scf_handoff(task_type: TaskType) -> bool:
    """Return whether a task can consume SCF handoff files."""

    return task_type in {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC}


def resolve_ecutrho_for_input(preset: AbacusInputPreset) -> Optional[float]:
    """Return explicit INPUT ecutrho, omitting generated defaults."""

    return preset.ecutrho


def resolve_out_stru_for_task(task_type: TaskType, preset: AbacusInputPreset) -> int:
    """Return whether ABACUS should write relaxed structure output."""

    if task_type == TaskType.RELAX:
        return 1
    return preset.out_stru


def out_chg_for_task(task_type: TaskType) -> int:
    """Return the default charge output flag for SCF-like tasks."""

    if task_type == TaskType.RELAX:
        return 0
    return 1


__all__ = [
    "AbacusInputSet",
    "CHARGE_HANDOFF_PATTERNS",
    "OPTIONAL_HANDOFF_FILES",
    "generate_abacus_inputs",
    "has_charge_handoff_files",
    "prepare_read_file_dir",
    "render_input_content",
    "render_kpt_content",
    "atom_coordinate_flags_for_task",
    "resolve_basis_type",
    "resolve_ecutrho_for_input",
    "resolve_out_stru_for_task",
    "resolve_ks_solver",
    "resolve_orbital_dir_for_input",
    "out_chg_for_task",
    "uses_scf_handoff",
]
