"""ABACUS log parser for phase-1 execution metrics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from autodft.core.enums import TaskType


FLOAT_PATTERN = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][-+]?\d+)?"
CONVERGENCE_PATTERNS = [
    r"\bconverged\b",
    r"charge\s+density\s+convergence\s+is\s+achieved",
]
TOTAL_ENERGY_EV_PATTERNS = [
    rf"TOTAL\s+ENERGY[^=]*=\s*({FLOAT_PATTERN})",
    rf"!?\s*FINAL(?:_|\s)+ETOT(?:_|\s)+IS\s*({FLOAT_PATTERN})",
]
FERMI_ENERGY_EV_PATTERNS = [
    rf"Fermi\s+energy[^=]*=\s*({FLOAT_PATTERN})",
    rf"\bEFERMI\s*=\s*({FLOAT_PATTERN})",
]
TOTAL_ENERGY_RY_PATTERNS = [
    rf"E_KS\(Ry\)\s*:\s*({FLOAT_PATTERN})",
]
BAND_GAP_EV_PATTERNS = [
    rf"band\s+gap[^=]*=\s*({FLOAT_PATTERN})",
]


DEFAULT_ABACUS_METRICS: Dict[str, Any] = {
    "converged": False,
    "total_energy_ev": None,
    "total_energy_ry": None,
    "fermi_energy_ev": None,
    "band_gap_ev": None,
    "output_files": [],
}


class AbacusLogParser:
    """Parse ABACUS output directories for basic run metrics."""

    def parse_task(self, task_type: TaskType, task_dir: str | Path, task_id: str) -> Dict[str, Any]:
        """Parse metrics from ``OUT.<task_id>`` under a task directory."""

        task_dir = Path(task_dir)
        out_dir = task_dir / f"OUT.{task_id}"
        text = load_running_log(out_dir)
        result = dict(DEFAULT_ABACUS_METRICS)

        if out_dir.is_dir():
            result["output_files"] = [str(path) for path in sorted(out_dir.iterdir()) if path.is_file()]

        if not text:
            return result

        if any(re.search(pattern, text, re.IGNORECASE) for pattern in CONVERGENCE_PATTERNS):
            result["converged"] = True

        energy_ev = find_last_float_any(text, TOTAL_ENERGY_EV_PATTERNS)
        if energy_ev is not None:
            result["total_energy_ev"] = energy_ev
        energy_ry = find_last_float_any(text, TOTAL_ENERGY_RY_PATTERNS)
        if energy_ry is not None:
            result["total_energy_ry"] = energy_ry

        fermi = find_last_float_any(text, FERMI_ENERGY_EV_PATTERNS)
        if fermi is not None:
            result["fermi_energy_ev"] = fermi

        if task_type == TaskType.BANDS:
            result["band_gap_ev"] = find_last_float_any(text, BAND_GAP_EV_PATTERNS)

        return result


def load_running_log(out_dir: Path) -> str:
    """Return the first ABACUS ``running_*.log`` text under an output directory."""

    if not out_dir.is_dir():
        return ""
    for path in sorted(out_dir.iterdir()):
        if path.is_file() and path.name.startswith("running_") and path.suffix == ".log":
            return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def find_last_float(text: str, pattern: str) -> Optional[float]:
    """Return the last float captured by a regex pattern."""

    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def find_last_float_any(text: str, patterns: list[str]) -> Optional[float]:
    """Return the last float captured by any regex pattern."""

    last_position = -1
    last_value: Optional[str] = None
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if match.start() > last_position:
                last_position = match.start()
                last_value = match.group(1)
    if last_value is None:
        return None
    try:
        return float(last_value)
    except ValueError:
        return None


__all__ = [
    "BAND_GAP_EV_PATTERNS",
    "AbacusLogParser",
    "CONVERGENCE_PATTERNS",
    "DEFAULT_ABACUS_METRICS",
    "FERMI_ENERGY_EV_PATTERNS",
    "FLOAT_PATTERN",
    "TOTAL_ENERGY_EV_PATTERNS",
    "TOTAL_ENERGY_RY_PATTERNS",
    "find_last_float_any",
    "find_last_float",
    "load_running_log",
]
