"""Shared enums for the phase-1 AutoDFT domain model.

These enums mirror the current prototype's supported workflow surface while
giving the new package explicit vocabulary for planners, executors, parsers,
and reports.
"""

from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    """Supported calculation task types.

    The phase-1 architecture keeps compatibility with the current prototype's
    task set: structural relaxation, SCF, bands, DOS, and elastic workflows.
    """

    RELAX = "relax"
    SCF = "scf"
    BANDS = "bands"
    DOS = "dos"
    ELASTIC = "elastic"


class TaskStatus(str, Enum):
    """Lifecycle status for planned and executed task nodes."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class BasisType(str, Enum):
    """ABACUS basis modes currently supported by the prototype."""

    PW = "pw"
    LCAO = "lcao"


class ArtifactType(str, Enum):
    """Known artifact categories exchanged between workflow stages."""

    CIF = "cif"
    STRU = "stru"
    INPUT = "input"
    KPT = "kpt"
    OUT_DIR = "out_dir"
    RUN_LOG = "run_log"
    WARNING_LOG = "warning_log"
    CHARGE_RESTART = "charge_restart"
    REPORT = "report"
    OTHER = "other"


__all__ = [
    "ArtifactType",
    "BasisType",
    "TaskStatus",
    "TaskType",
]

