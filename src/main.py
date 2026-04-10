# 主程序入口，负责解析命令行参数，加载配置文件，并调用 pipeline 运行整个流程

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from pipeline import run_pipeline


def _parse_args():
    parser = argparse.ArgumentParser(description="Isolated ABACUS agent prototype (Step 2 + Step 3)")
    parser.add_argument("--query", required=True, help="Natural-language scientific query")
    parser.add_argument("--structure", required=True, help="Path to ABACUS STRU file")
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
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    base_dir = cfg_path.resolve().parent
    abacus_cfg = cfg.get("abacus", {})
    for key in ("pseudo_dir", "orb_dir", "orbital_dir"):
        value = abacus_cfg.get(key)
        if value and not Path(value).expanduser().is_absolute():
            abacus_cfg[key] = str((base_dir / value).resolve())
    cfg["abacus"] = abacus_cfg
    return cfg


def main():
    args = _parse_args()
    cfg = _load_config(args.config)
    task_plan = [item.strip() for item in args.tasks.split(",") if item.strip()] or None
    result = run_pipeline(
        query=args.query,
        structure_path=args.structure,
        work_dir=args.work_dir,
        cfg=cfg,
        task_plan=task_plan,
    )

    print(result.summary)
    if result.report_path:
        print(f"Report: {result.report_path}")

    print(json.dumps({
        "query": result.query,
        "task_count": len(result.tasks),
        "report_path": result.report_path,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
