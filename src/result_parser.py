# ABACUS 结果解析器，负责从 ABACUS 输出中提取关键信息
#
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from schema import TaskType


def parse_abacus_result(task_type: TaskType, task_dir: Path) -> Dict[str, Any]:
    out_dir = task_dir / "OUT.ABACUS"
    text = _load_running_log(out_dir)

    result: Dict[str, Any] = {
        "converged": False,
        "total_energy_ev": None,
        "total_energy_ry": None,
        "fermi_energy_ev": None,
        "band_gap_ev": None,
        "output_files": [],
    }

    if not text:
        return result

    if re.search(r"converged", text, re.IGNORECASE):
        result["converged"] = True

    energy_ev = _find_last_float(text, r"TOTAL\s+ENERGY[^=]*=\s*([-+]?\d+\.?\d*(?:[Ee][-+]?\d+)?)")
    if energy_ev is not None:
        result["total_energy_ev"] = energy_ev
    energy_ry = _find_last_float(text, r"E_KS\(Ry\)\s*:\s*([-+]?\d+\.?\d*(?:[Ee][-+]?\d+)?)")
    if energy_ry is not None:
        result["total_energy_ry"] = energy_ry

    fermi = _find_last_float(text, r"Fermi\s+energy[^=]*=\s*([-+]?\d+\.?\d*(?:[Ee][-+]?\d+)?)")
    if fermi is not None:
        result["fermi_energy_ev"] = fermi

    if task_type == TaskType.BANDS:
        result["band_gap_ev"] = _find_band_gap(text)

    if out_dir.is_dir():
        result["output_files"] = [str(path) for path in sorted(out_dir.iterdir()) if path.is_file()]

    return result


def _load_running_log(out_dir: Path) -> str:
    if not out_dir.is_dir():
        return ""
    for path in sorted(out_dir.iterdir()):
        if path.is_file() and path.name.startswith("running_") and path.suffix == ".log":
            return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def _find_last_float(text: str, pattern: str):
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def _find_band_gap(text: str):
    gap = _find_last_float(text, r"band\s+gap[^=]*=\s*([-+]?\d+\.?\d*(?:[Ee][-+]?\d+)?)")
    return gap
