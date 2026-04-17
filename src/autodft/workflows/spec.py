"""Workflow execution configuration and small path helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from autodft.abacus.presets import AbacusInputPreset
from autodft.abacus.resources import AbacusResourceConfig
from autodft.abacus.runner import AbacusRunConfig


@dataclass
class WorkflowExecutionConfig:
    """Minimal runtime configuration for the phase-1 workflow executor."""

    work_dir: str
    abacus_resources: AbacusResourceConfig
    abacus_preset: AbacusInputPreset
    abacus_run: AbacusRunConfig
    stop_on_failure: bool = False
    raw_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, work_dir: str, cfg: Optional[Dict[str, Any]] = None) -> "WorkflowExecutionConfig":
        """Create executor config from the current repository config shape."""

        cfg = dict(cfg or {})
        abacus_cfg = dict(cfg.get("abacus", {}))
        defaults = dict(cfg.get("defaults", {}).get("calculation", {}))
        pseudo_dir = str(abacus_cfg.get("pseudo_dir", ""))
        orb_dir = str(abacus_cfg.get("orb_dir", abacus_cfg.get("orbital_dir", "")))
        return cls(
            work_dir=work_dir,
            abacus_resources=AbacusResourceConfig(pseudo_dir=pseudo_dir, orb_dir=orb_dir),
            abacus_preset=AbacusInputPreset.from_mapping(defaults),
            abacus_run=AbacusRunConfig(
                executable=str(abacus_cfg.get("executable", "abacus")),
                run_mode=str(abacus_cfg.get("run_mode", "mpirun")),
                np=int(abacus_cfg.get("np", 8)),
                use_hwthread_cpus=bool(abacus_cfg.get("use_hwthread_cpus", False)),
                oversubscribe=bool(abacus_cfg.get("oversubscribe", False)),
            ),
            stop_on_failure=bool(cfg.get("stop_on_failure", False)),
            raw_config=cfg,
        )

    @property
    def root(self) -> Path:
        """Return the absolute workflow root directory."""

        return Path(self.work_dir).resolve()


@dataclass
class TaskRuntimePaths:
    """Filesystem paths associated with one task execution."""

    task_dir: Path
    structure_path: Path
    dependency_task_id: Optional[str] = None
    dependency_task_dir: Optional[Path] = None


__all__ = ["TaskRuntimePaths", "WorkflowExecutionConfig"]
