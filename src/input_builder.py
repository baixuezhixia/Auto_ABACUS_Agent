#把一个任务变成 ABACUS 需要的 INPUT、STRU、KPT 三个文件

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from schema import CalcTask, TaskType
from resource_manager import resolve_orbital_map, resolve_pseudo_map


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
    ecutrho = default_cfg.get("ecutrho", int(float(ecut) * 8))
    kmesh = default_cfg.get("kmesh", [6, 6, 6])
    kpath = default_cfg.get("kpath", _default_kpath())
    latname = default_cfg.get("latname", "fcc")
    smearing_method = default_cfg.get("smearing_method", "gaussian")
    smearing_sigma = default_cfg.get("smearing_sigma", 0.01)
    scf_thr = default_cfg.get("scf_thr", 1e-7)
    scf_nmax = default_cfg.get("scf_nmax", 50)
    ks_solver = default_cfg.get("ks_solver", "cg")
    nspin = default_cfg.get("nspin", 1)
    symmetry = default_cfg.get("symmetry", 1)
    out_level = default_cfg.get("out_level", "ie")
    relax_force_thr = default_cfg.get("relax_force_thr", 0.01)
    stress_thr = default_cfg.get("stress_thr", 10)

    structure_text = structure_path.read_text(encoding="utf-8")
    species = _extract_species(structure_text)
    pseudo_map = resolve_pseudo_map(species, pseudo_dir)
    orb_map = resolve_orbital_map(species, orb_dir) if orb_dir else {}

    calculation = _abacus_calculation(task.task_type)
    out_stru = default_cfg.get("out_stru", 0)
    is_followup = task.task_type in {TaskType.BANDS, TaskType.DOS}
    init_chg = "file" if is_followup else "atomic"
    if task.task_type == TaskType.BANDS:
        # Line-mode k-paths require symmetry off in ABACUS.
        symmetry = 0
    read_file_dir = None
    if dependency_task_dir is not None and dependency_task_id and is_followup:
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
        "basis_type pw",
        f"calculation {calculation}",
        f"latname {latname}",
        f"ecutwfc {ecut}",
        f"ecutrho {ecutrho}",
        f"scf_thr {scf_thr}",
        f"scf_nmax {scf_nmax}",
        f"ks_solver {ks_solver}",
        f"nspin {nspin}",
        f"symmetry {symmetry}",
        f"out_level {out_level}",
        f"out_stru {out_stru}",
    ]

    if task.task_type in {TaskType.SCF, TaskType.RELAX}:
        input_lines.extend([
            f"smearing_method {smearing_method}",
        ])
        if smearing_method != "fixed":
            input_lines.append(f"smearing_sigma {smearing_sigma}")
        input_lines.append("out_chg 1")

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

    input_content = "\n".join(input_lines) + "\n"

    kpt_content = _build_kpt_content(kmesh, kpath, task.task_type)
    stru_content = _render_stru(
        structure_text,
        species,
        pseudo_map,
        orb_map,
        include_numerical_orbital=False,
    )

    input_path = task_dir / "INPUT"
    stru_path = task_dir / "STRU"
    kpt_path = task_dir / "KPT"
    input_path.write_text(input_content, encoding="utf-8")
    stru_path.write_text(stru_content, encoding="utf-8")
    kpt_path.write_text(kpt_content, encoding="utf-8")
    return input_path, stru_path, kpt_path


def _abacus_calculation(task_type: TaskType) -> str:
    if task_type == TaskType.SCF:
        return "scf"
    if task_type == TaskType.RELAX:
        return "relax"
    if task_type == TaskType.BANDS:
        return "nscf"
    if task_type == TaskType.DOS:
        return "nscf"
    if task_type == TaskType.ELASTIC:
        # Placeholder: elastic needs strain loop + postproc, not a single ABACUS mode.
        return "scf"
    return "scf"


def _build_kpt_content(kmesh, kpath, task_type: TaskType) -> str:
    if task_type == TaskType.BANDS:
        lines = ["K_POINTS", str(len(kpath)), "Line_Cartesian"]
        for point in kpath:
            lines.append(f"{point[0]} {point[1]} {point[2]} {point[3]}")
        return "\n".join(lines) + "\n"

    if task_type == TaskType.DOS:
        return f"""K_POINTS
0
Gamma
{kmesh[0]} {kmesh[1]} {kmesh[2]} 0 0 0
"""

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
            if line.upper().startswith(("LATTICE", "ATOMIC_POSITIONS", "CELL_PARAMETERS", "K_POINTS")):
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
) -> str:
    lines = structure_text.splitlines()
    output: List[str] = []
    in_species = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.upper().startswith("ATOMIC_SPECIES"):
            in_species = True
            output.append(line)
            continue
        if in_species:
            if not stripped or stripped.upper().startswith(("LATTICE", "ATOMIC_POSITIONS", "CELL_PARAMETERS", "K_POINTS")):
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
            orb_name = Path(orb_map[element]).name
            output.append(orb_name)

    return "\n".join(output).rstrip() + "\n"


def _prepare_read_file_dir(task_id: str, source_out_dir: Path, task_dir: Path) -> Optional[Path]:
    if not source_out_dir.is_dir():
        return None

    staging_dir = task_dir / "READ_CHG"
    staging_dir.mkdir(parents=True, exist_ok=True)

    # ABACUS prefers restart file named with the current suffix.
    restart_candidates = sorted(source_out_dir.glob("*-CHARGE-DENSITY.restart"))
    if restart_candidates:
        src = restart_candidates[0]
        dst = staging_dir / f"{task_id}-CHARGE-DENSITY.restart"
        dst.write_bytes(src.read_bytes())

    # Keep cube files as a fallback for init_chg=file.
    for cube_name in ("chg.cube", "chg1.cube", "chg2.cube"):
        cube_path = source_out_dir / cube_name
        if cube_path.is_file():
            (staging_dir / cube_name).write_bytes(cube_path.read_bytes())

    return staging_dir
