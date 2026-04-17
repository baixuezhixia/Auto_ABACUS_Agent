"""Command-line entrypoint for the phase-1 AutoDFT architecture."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional, Sequence

import yaml

from autodft.abacus.presets import normalize_kmesh
from autodft.core.enums import TaskType
from autodft.core.exceptions import AutoDFTError
from autodft.core.models import WorkflowSpec
from autodft.planners.base import WorkflowPlanner
from autodft.planners.normalizer import normalize_workflow, task_node_from_type
from autodft.planners.rule_planner import RulePlanner, detect_basis_type
from autodft.reports import build_summary_text
from autodft.structures import StructureResolver
from autodft.workflows import run_basic_workflow


class ManualTaskPlanner(WorkflowPlanner):
    """Planner adapter for the current ``--tasks`` CLI override."""

    def __init__(self, task_names: Sequence[str]) -> None:
        self.task_names = [name.strip().lower() for name in task_names if name.strip()]

    def plan(self, query: str, workflow_id: Optional[str] = None) -> WorkflowSpec:
        """Build a normalized workflow from explicit task names."""

        basis_type = detect_basis_type(query)
        tasks = [
            task_node_from_type(
                TaskType(name),
                params={"basis_type": basis_type.value} if basis_type else None,
                basis_type=basis_type,
            )
            for name in self.task_names
        ]
        return normalize_workflow(query=query, tasks=tasks, workflow_id=workflow_id)


def parse_args(argv: Optional[Sequence[str]] = None):
    """Parse the new CLI while preserving the current core arguments."""

    parser = argparse.ArgumentParser(description="AutoDFT phase-1 workflow executor")
    parser.add_argument("--query", required=True, help="Natural-language scientific query")
    parser.add_argument(
        "--structure",
        required=True,
        help="Local .cif, local ABACUS STRU/.stru, Materials Project material ID, or formula",
    )
    parser.add_argument("--work-dir", default="./runs", help="Working directory for generated tasks")
    parser.add_argument("--config", default="config.yaml", help="YAML config path")
    parser.add_argument(
        "--tasks",
        default="",
        help="Comma-separated task list, e.g. scf,relax,bands,dos,elastic. If set, bypasses rule planning.",
    )
    parser.add_argument(
        "--kmesh",
        default="",
        help="Override the generated KPT mesh, e.g. 1,1,1 or 1x1x1 for Gamma-only debugging.",
    )
    return parser.parse_args(argv)


def load_config(path: str) -> Dict[str, Any]:
    """Load a repository config file and normalize path/env behavior."""

    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    raw_text = cfg_path.read_text(encoding="utf-8")
    yaml_text = _strip_env_assignments(raw_text)
    cfg = yaml.safe_load(yaml_text) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"Config root must be a mapping: {cfg_path}")

    for key, value in _parse_env_assignments(raw_text).items():
        cfg.setdefault(key, value)

    base_dir = cfg_path.resolve().parent
    abacus_cfg = dict(cfg.get("abacus", {}))
    for key in ("pseudo_dir", "orb_dir", "orbital_dir"):
        value = abacus_cfg.get(key)
        if value and not _is_absolute_path_like(str(value)):
            abacus_cfg[key] = str((base_dir / str(value)).resolve())
    cfg["abacus"] = abacus_cfg

    _export_config_env(cfg)
    return cfg


def run_cli(
    argv: Optional[Sequence[str]] = None,
    *,
    resolver: Optional[StructureResolver] = None,
    run_func=None,
):
    """Run the phase-1 CLI and return the run summary.

    ``resolver`` and ``run_func`` are injectable for integration tests and
    future embedding; normal command-line use leaves them unset.
    """

    args = parse_args(argv)
    cfg = load_config(args.config)
    if args.kmesh:
        _apply_kmesh_override(cfg, args.kmesh)
    task_plan = [item.strip() for item in args.tasks.split(",") if item.strip()]
    planner: WorkflowPlanner = ManualTaskPlanner(task_plan) if task_plan else RulePlanner()
    summary = run_basic_workflow(
        query=args.query,
        structure_input=args.structure,
        work_dir=args.work_dir,
        cfg=cfg,
        planner=planner,
        resolver=resolver,
        run_func=run_func,
    )
    print(build_summary_text(summary))
    return summary


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    resolver: Optional[StructureResolver] = None,
    run_func=None,
) -> None:
    """Console entrypoint."""

    try:
        run_cli(argv, resolver=resolver, run_func=run_func)
    except (AutoDFTError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from exc


def _is_absolute_path_like(value: str) -> bool:
    if value.startswith("/"):
        return True
    return Path(value).expanduser().is_absolute()


def _apply_kmesh_override(cfg: Dict[str, Any], raw_kmesh: str) -> None:
    """Apply a CLI k-point mesh override to the existing calculation defaults."""

    defaults = cfg.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("Config key 'defaults' must be a mapping when --kmesh is used.")
    calculation = defaults.setdefault("calculation", {})
    if not isinstance(calculation, dict):
        raise ValueError("Config key 'defaults.calculation' must be a mapping when --kmesh is used.")
    calculation["kmesh"] = normalize_kmesh(raw_kmesh)


def _strip_env_assignments(text: str) -> str:
    lines = []
    pattern = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*(['\"]).*\1\s*$")
    for line in text.splitlines():
        if pattern.match(line.strip()):
            continue
        lines.append(line)
    return "\n".join(lines)


def _parse_env_assignments(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['\"])(.*)\2\s*$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if match:
            values[match.group(1)] = match.group(3)
    return values


def _export_config_env(cfg: Dict[str, Any]) -> None:
    mp_api_key = str(cfg.get("MP_API_KEY") or cfg.get("mp_api_key") or "").strip()
    if mp_api_key and not os.environ.get("MP_API_KEY"):
        os.environ["MP_API_KEY"] = mp_api_key


if __name__ == "__main__":
    main()
