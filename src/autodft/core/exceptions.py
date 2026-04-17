"""Exception hierarchy for the phase-1 AutoDFT package.

The current runtime raises built-in exceptions directly. Future migrated code
can raise these typed errors at package boundaries while preserving useful
messages for the CLI and report layer.
"""

from __future__ import annotations


class AutoDFTError(Exception):
    """Base class for AutoDFT-specific failures."""


class ConfigurationError(AutoDFTError):
    """Raised when configuration is missing, invalid, or inconsistent."""


class PlanningError(AutoDFTError):
    """Raised when task decoding or workflow planning cannot produce a plan."""


class StructureResolutionError(AutoDFTError):
    """Raised when a requested structure cannot be resolved or converted."""


class InputGenerationError(AutoDFTError):
    """Raised when ABACUS input files cannot be generated."""


class ExecutionError(AutoDFTError):
    """Raised when task execution cannot be launched or classified."""


class ParsingError(AutoDFTError):
    """Raised when output parsing fails in a non-recoverable way."""


class ReportingError(AutoDFTError):
    """Raised when a workflow report cannot be assembled or written."""


__all__ = [
    "AutoDFTError",
    "ConfigurationError",
    "ExecutionError",
    "InputGenerationError",
    "ParsingError",
    "PlanningError",
    "ReportingError",
    "StructureResolutionError",
]

