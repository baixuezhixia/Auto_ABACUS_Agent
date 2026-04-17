"""Command-line entrypoints and argument handling."""

from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = ["load_config", "parse_args", "run_cli"]


def __getattr__(name: str) -> Any:
    """Lazily expose CLI helpers without pre-importing ``autodft.cli.main``."""

    if name in __all__:
        main_module = import_module("autodft.cli.main")
        return getattr(main_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
