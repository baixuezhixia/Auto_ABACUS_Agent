from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from resource_manager import resolve_orbital_map, resolve_pseudo_map
from schema import CalcTask, TaskType


VALID_BASIS_TYPES = {"pw", "lcao"}
DEFAULT_PW_KS_SOLVER = "cg"
DEFAULT_LCAO_KS_SOLVER = "genelpa"
MOVABLE_ATOM_FLAGS = ("1", "1", "1")


def build_task_inputs(
    task: CalcTask,
    task_dir: Path,
    structure_path: Path,
    default_cfg: Dict,
    pseudo_dir: str,
    orb_dir: str,
    dependency_task_dir: Optional[Path] = None,
    dependency_task_id: Optional[str] = None,
) -> Tuple[Path, Path, Path]:
    task_dir.mkdir(parents=True, exist_ok=True)

    ecut = default_cfg.get("ecutwfc", 80)
    kmesh = default_cfg.get("kmesh", [6, 6, 6])
    kpath = default_cfg.get("kpath", _default_kpath())
    latname = default_cfg.get("latname", "fcc")
    smearing_method = default_cfg.get("smearing_method", "gaussian")
    smearing_sigma = default_cfg.get("smearing_sigma", 0.01)
    scf_thr = default_cfg.get("scf_thr", 1e-7)
    scf_nmax = default_cfg.get("scf_nmax", 50)
    nspin = default_cfg.get("nspin", 1)
    symmetry = default_cfg.get("symmetry", 1)
    out_level = default_cfg.get("out_level", "ie")
    out_stru = default_cfg.get("out_stru", 0)
    relax_force_thr = default_cfg.get("relax_force_thr", 0.01)
    stress_thr = default_cfg.get("stress_thr", 10)
    basis_type = _resolve_basis_type(task, default_cfg, orb_dir)
    ecutrho = _resolve_ecutrho_for_input(default_cfg)
    ks_solver = _resolve_ks_solver(basis_type, default_cfg)
    out_stru = _resolve_out_stru_for_task(task.task_type, out_stru)
    orbital_dir = _resolve_orbital_dir_for_input(basis_type, orb_dir)
    include_numerical_orbital = basis_type == "lcao"

    structure_text = structure_path.read_text(encoding="utf-8")
    species = _extract_species(structure_text)
    pseudo_map = resolve_pseudo_map(species, pseudo_dir)
    orb_map = resolve_orbital_map(species, orb_dir) if include_numerical_orbital else {}

    calculation = _abacus_calculation(task)
    is_followup = task.task_type in {TaskType.BANDS, TaskType.DOS}
    uses_scf_handoff = task.task_type in {TaskType.BANDS, TaskType.DOS, TaskType.ELASTIC}
    init_chg = "file" if is_followup else "atomic"
    if task.task_type == TaskType.BANDS:
        symmetry = 0
    read_file_dir = None
    if dependency_task_dir is not None and dependency_task_id and uses_scf_handoff:
        source_out_dir = dependency_task_dir / f"OUT.{dependency_task_id}"
        read_file_dir = _prepare_read_file_dir(
            task_id=task.task_id,
            source_out_dir=source_out_dir,
            task_dir=task_dir,
        )

    input_lines = [
        "INPUT_PARAMETERS",
        f"suffix {task.task_id}",
        "stru_file STRU",
        "kpoint_file KPT",
        f"pseudo_dir {pseudo_dir}",
        f"basis_type {basis_type}",
        f"calculation {calculation}",
        f"ecutwfc {ecut}",
        f"scf_thr {scf_thr}",
        f"scf_nmax {scf_nmax}",
        f"ks_solver {ks_solver}",
        f"nspin {nspin}",
        f"symmetry {symmetry}",
        f"out_level {out_level}",
        f"out_stru {out_stru}",
    ]
    if ecutrho is not None:
        input_lines.insert(8, f"ecutrho {ecutrho}")
    if orbital_dir is not None:
        input_lines.append(f"orbital_dir {orbital_dir}")
    if "LATTICE_VECTORS" not in structure_text.upper():
        input_lines.append(f"latname {latname}")

    if task.task_type in {TaskType.SCF, TaskType.RELAX}:
        input_lines.append(f"smearing_method {smearing_method}")
        if smearing_method != "fixed":
            input_lines.append(f"smearing_sigma {smearing_sigma}")
        input_lines.append(f"out_chg {_out_chg_for_task(task.task_type)}")

    if task.task_type == TaskType.RELAX:
        input_lines.extend([
            f"force_thr_ev {relax_force_thr}",
            "relax_method cg 1",
        ])

    if task.task_type == TaskType.ELASTIC:
        input_lines.extend([
            f"force_thr_ev {relax_force_thr}",
            f"stress_thr {stress_thr}",
            "relax_method cg 1",
        ])

    if task.task_type in {TaskType.BANDS, TaskType.DOS}:
        input_lines.append(f"init_chg {init_chg}")
        if read_file_dir is not None:
            input_lines.append(f"read_file_dir {read_file_dir}")
        input_lines.append("out_chg 0")
        if task.task_type == TaskType.BANDS:
            input_lines.append("out_band 1")
        if task.task_type == TaskType.DOS:
            input_lines.extend([
                "out_dos 1",
                f"dos_emin_ev {default_cfg.get('dos_emin_ev', -15.0)}",
                f"dos_emax_ev {default_cfg.get('dos_emax_ev', 15.0)}",
                f"dos_edelta_ev {default_cfg.get('dos_edelta_ev', 0.01)}",
            ])
    elif task.task_type == TaskType.ELASTIC and read_file_dir is not None:
        input_lines.append("init_chg file")
        input_lines.append(f"read_file_dir {read_file_dir}")

    input_content = "\n".join(input_lines) + "\n"

    kpt_content = _build_kpt_content(kmesh, kpath, task.task_type)
    stru_content = _render_stru(
        structure_text,
        species,
        pseudo_map,
        orb_map,
        include_numerical_orbital=include_numerical_orbital,
        atom_coordinate_flags=_atom_coordinate_flags_for_task(task.task_type),
    )

    input_path = task_dir / "INPUT"
    stru_path = task_dir / "STRU"
    kpt_path = task_dir / "KPT"
    input_path.write_text(input_content, encoding="utf-8")
    stru_path.write_text(stru_content, encoding="utf-8")
    kpt_path.write_text(kpt_content, encoding="utf-8")
    return input_path, stru_path, kpt_path


def _resolve_basis_type(task: CalcTask, default_cfg: Dict, orb_dir: str) -> str:
    raw_basis_type = task.params.get("basis_type", default_cfg.get("basis_type", "pw"))
    basis_type = str(raw_basis_type).strip().lower()
    if basis_type not in VALID_BASIS_TYPES:
        raise ValueError(f"Unsupported basis_type '{raw_basis_type}'. Expected one of: {sorted(VALID_BASIS_TYPES)}")
    if basis_type == "lcao" and not orb_dir:
        raise ValueError("basis_type 'lcao' requires abacus.orb_dir or abacus.orbital_dir to be configured")
    return basis_type


def _resolve_ks_solver(basis_type: str, default_cfg: Dict) -> str:
    if default_cfg.get("ks_solver"):
        return str(default_cfg["ks_solver"])
    if basis_type == "lcao":
        return DEFAULT_LCAO_KS_SOLVER
    return DEFAULT_PW_KS_SOLVER


def _resolve_ecutrho_for_input(default_cfg: Dict) -> Optional[float]:
    return default_cfg.get("ecutrho")


def _resolve_out_stru_for_task(task_type: TaskType, configured_out_stru) -> int:
    if task_type == TaskType.RELAX:
        return 1
    return configured_out_stru


def _out_chg_for_task(task_type: TaskType) -> int:
    if task_type == TaskType.RELAX:
        return 0
    return 1


def _resolve_orbital_dir_for_input(basis_type: str, orb_dir: str) -> Optional[str]:
    if basis_type != "lcao":
        return None
    return str(Path(orb_dir).expanduser().resolve())


def _abacus_calculation(task: CalcTask) -> str:
    calculation = task.params.get("calculation")
    if calculation:
        return str(calculation)
    task_type = task.task_type
    if task_type == TaskType.SCF:
        return "scf"
    if task_type == TaskType.RELAX:
        return "relax"
    if task_type == TaskType.BANDS:
        return "nscf"
    if task_type == TaskType.DOS:
        return "nscf"
    if task_type == TaskType.ELASTIC:
        return "scf"
    return "scf"


def _build_kpt_content(kmesh, kpath, task_type: TaskType) -> str:
    if task_type == TaskType.BANDS:
        lines = ["K_POINTS", str(len(kpath)), "Line_Cartesian"]
        for point in kpath:
            lines.append(f"{point[0]} {point[1]} {point[2]} {point[3]}")
        return "\n".join(lines) + "\n"

    return f"""K_POINTS
0
Gamma
{kmesh[0]} {kmesh[1]} {kmesh[2]} 0 0 0
"""


def _default_kpath() -> List[Tuple[float, float, float, int]]:
    return [
        (0.0, 0.0, 0.0, 20),
        (0.5, 0.0, 0.0, 20),
        (0.5, 0.5, 0.0, 20),
        (0.0, 0.0, 0.0, 1),
    ]


def _extract_species(structure_text: str) -> List[str]:
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
        raise ValueError("No ATOMIC_SPECIES block found in structure file")
    return species


def _render_stru(
    structure_text: str,
    species: Iterable[str],
    pseudo_map: Dict[str, str],
    orb_map: Dict[str, str],
    include_numerical_orbital: bool,
    atom_coordinate_flags: Optional[Tuple[str, str, str]] = None,
) -> str:
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
                if stripped:
                    output.append(line)
                else:
                    output.append("")
            continue
        if in_species:
            if not stripped or stripped.upper().startswith(("LATTICE", "ATOMIC_POSITIONS", "CELL_PARAMETERS", "K_POINTS", "NUMERICAL_ORBITAL")):
                in_species = False
                if stripped:
                    output.append(line)
                else:
                    output.append("")
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
        rendered = _set_atomic_position_flags(rendered, atom_coordinate_flags)
    return rendered


def _atom_coordinate_flags_for_task(task_type: TaskType) -> Optional[Tuple[str, str, str]]:
    if task_type == TaskType.RELAX:
        return MOVABLE_ATOM_FLAGS
    return None


def _set_atomic_position_flags(structure_text: str, flags: Tuple[str, str, str]) -> str:
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


def _prepare_read_file_dir(task_id: str, source_out_dir: Path, task_dir: Path) -> Optional[str]:
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

    onsite_dm = source_out_dir / "onsite.dm"
    if onsite_dm.is_file():
        (staging_dir / "onsite.dm").write_bytes(onsite_dm.read_bytes())

    return "READ_CHG" if copied_charge else None
