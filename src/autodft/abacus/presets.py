"""ABACUS calculation presets separated from file rendering."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
import re
from typing import Any, Dict, List, Optional, Tuple

from autodft.core.enums import BasisType, TaskType


KPathPoint = Tuple[float, float, float, int]
DEFAULT_PW_KS_SOLVER = "cg"
DEFAULT_LCAO_KS_SOLVER = "genelpa"


@dataclass
class AbacusInputPreset:
    """Default ABACUS parameters for generated task inputs.

    The fields mirror the current prototype defaults. Rendering modules consume
    this preset but do not own the policy for default values.
    """

    basis_type: BasisType = BasisType.PW
    ecutwfc: float = 80
    ecutrho: float | None = None
    kmesh: List[int] = field(default_factory=lambda: [6, 6, 6])
    kpath: List[KPathPoint] = field(default_factory=lambda: list(default_kpath()))
    latname: str = "fcc"
    smearing_method: str = "gaussian"
    smearing_sigma: float = 0.01
    scf_thr: float = 1e-7
    scf_nmax: int = 50
    ks_solver: Optional[str] = None
    nspin: int = 1
    symmetry: int = 1
    out_level: str = "ie"
    out_stru: int = 0
    relax_force_thr: float = 0.01
    stress_thr: float = 10
    dos_emin_ev: float = -15.0
    dos_emax_ev: float = 15.0
    dos_edelta_ev: float = 0.01

    @classmethod
    def from_mapping(cls, data: Dict[str, Any] | None) -> "AbacusInputPreset":
        """Build a preset from the current ``defaults.calculation`` mapping."""

        data = dict(data or {})
        basis_value = str(data.pop("basis_type", BasisType.PW.value)).lower()
        if basis_value not in {item.value for item in BasisType}:
            raise ValueError(f"Unsupported basis_type '{basis_value}'.")
        if "kmesh" in data:
            data["kmesh"] = normalize_kmesh(data["kmesh"])
        if "kpath" in data:
            data["kpath"] = [tuple(item) for item in data["kpath"]]
        allowed_fields = {item.name for item in fields(cls)}
        filtered = {key: value for key, value in data.items() if key in allowed_fields}
        return cls(basis_type=BasisType(basis_value), **filtered)

    @property
    def resolved_ecutrho(self) -> float:
        """Return explicit ecutrho or the legacy 8x ecutwfc fallback."""

        return self.ecutrho if self.ecutrho is not None else float(self.ecutwfc) * 8


def default_kpath() -> List[KPathPoint]:
    """Return the current default high-symmetry path used for band tasks."""

    return [
        (0.0, 0.0, 0.0, 20),
        (0.5, 0.0, 0.0, 20),
        (0.5, 0.5, 0.0, 20),
        (0.0, 0.0, 0.0, 1),
    ]


def normalize_kmesh(value: Any) -> List[int]:
    """Normalize a user-provided three-integer k-point mesh."""

    if isinstance(value, str):
        parts = [part for part in re.split(r"[\s,xX]+", value.strip()) if part]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise ValueError("kmesh must be a three-integer list or string, for example [1, 1, 1].")

    if len(parts) != 3:
        raise ValueError("kmesh must contain exactly three integers, for example [1, 1, 1].")

    try:
        mesh = [int(part) for part in parts]
    except (TypeError, ValueError) as exc:
        raise ValueError("kmesh values must be integers, for example [1, 1, 1].") from exc

    if any(item <= 0 for item in mesh):
        raise ValueError("kmesh values must be positive integers.")
    return mesh


def calculation_for_task(task_type: TaskType, params: Dict[str, Any] | None = None) -> str:
    """Return ABACUS calculation mode for a task type."""

    calculation = (params or {}).get("calculation")
    if calculation:
        return str(calculation)
    if task_type == TaskType.RELAX:
        return "relax"
    if task_type in {TaskType.BANDS, TaskType.DOS}:
        return "nscf"
    return "scf"


def is_followup_task(task_type: TaskType) -> bool:
    """Return whether a task reads charge from an upstream calculation."""

    return task_type in {TaskType.BANDS, TaskType.DOS}


def default_ks_solver_for_basis(basis_type: BasisType) -> str:
    """Return a conservative default solver for an ABACUS basis type."""

    if basis_type == BasisType.LCAO:
        return DEFAULT_LCAO_KS_SOLVER
    return DEFAULT_PW_KS_SOLVER


__all__ = [
    "AbacusInputPreset",
    "DEFAULT_LCAO_KS_SOLVER",
    "DEFAULT_PW_KS_SOLVER",
    "KPathPoint",
    "calculation_for_task",
    "default_ks_solver_for_basis",
    "default_kpath",
    "is_followup_task",
    "normalize_kmesh",
]
