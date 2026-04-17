"""Compatibility wrapper for the phase-1 CLI."""

from autodft.cli.main import load_config, main, parse_args, run_cli

__all__ = ["load_config", "main", "parse_args", "run_cli"]


if __name__ == "__main__":
    main()
