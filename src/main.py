from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import yaml

from pipeline import run_pipeline


def _parse_args():
    parser = argparse.ArgumentParser(description="Isolated ABACUS agent prototype (Step 2 + Step 3)")
    parser.add_argument("--query", required=True, help="Natural-language scientific query")
    parser.add_argument(
        "--structure",
        required=True,
        help="Materials Project material ID or formula, e.g. mp-149 or Si.",
    )
    parser.add_argument("--work-dir", default="./runs", help="Working directory for generated tasks")
    parser.add_argument("--config", default="config.yaml", help="YAML config path")
    parser.add_argument(
        "--tasks",
        default="",
        help="Comma-separated task list, e.g. scf,relax,bands,dos,elastic. If set, bypasses decoding.",
    )
    return parser.parse_args()


def _load_config(path: str):
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    raw_text = cfg_path.read_text(encoding="utf-8")
    yaml_text = _strip_env_assignments(raw_text)
    cfg = yaml.safe_load(yaml_text) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"Config root must be a mapping: {cfg_path}")

    env_assignments = _parse_env_assignments(raw_text)
    for key, value in env_assignments.items():
        cfg.setdefault(key, value)

    base_dir = cfg_path.resolve().parent
    abacus_cfg = cfg.get("abacus", {})
    for key in ("pseudo_dir", "orb_dir", "orbital_dir"):
        value = abacus_cfg.get(key)
        if value and not _is_absolute_path_like(str(value)):
            abacus_cfg[key] = str((base_dir / value).resolve())
    cfg["abacus"] = abacus_cfg

    _export_config_env(cfg)
    return cfg


def _is_absolute_path_like(value: str) -> bool:
    if value.startswith("/"):
        return True
    return Path(value).expanduser().is_absolute()


def _strip_env_assignments(text: str) -> str:
    lines = []
    pattern = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*(['\"]).*\1\s*$")
    for line in text.splitlines():
        if pattern.match(line.strip()):
            continue
        lines.append(line)
    return "\n".join(lines)


def _parse_env_assignments(text: str):
    values = {}
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['\"])(.*)\2\s*$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if match:
            values[match.group(1)] = match.group(3)
    return values


def _export_config_env(cfg: dict) -> None:
    mp_api_key = str(cfg.get("MP_API_KEY") or cfg.get("mp_api_key") or "").strip()
    if mp_api_key and not os.environ.get("MP_API_KEY"):
        os.environ["MP_API_KEY"] = mp_api_key


def main():
    args = _parse_args()
    cfg = _load_config(args.config)
    task_plan = [item.strip() for item in args.tasks.split(",") if item.strip()] or None
    result = run_pipeline(
        query=args.query,
        structure_input=args.structure,
        work_dir=args.work_dir,
        cfg=cfg,
        task_plan=task_plan,
    )

    print(result.summary)
    for notice in result.notices:
        print(f"Notice: {notice}")
    if result.structure_artifact:
        print(f"Downloaded CIF: {result.structure_artifact.cif_path}")
    if result.report_path:
        print(f"Report: {result.report_path}")

    print(json.dumps({
        "query": result.query,
        "task_count": len(result.tasks),
        "report_path": result.report_path,
        "structure": {
            "material_id": result.structure_artifact.material_id if result.structure_artifact else None,
            "cif_path": result.structure_artifact.cif_path if result.structure_artifact else None,
            "lattice_type": result.structure_artifact.lattice_type if result.structure_artifact else None,
        },
        "notices": result.notices,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
