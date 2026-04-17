from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class CliModuleInvocationTests(unittest.TestCase):
    def test_python_m_autodft_cli_main_does_not_warn_about_preimported_module(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.run(
            [sys.executable, "-m", "autodft.cli.main", "--help"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0)
        self.assertIn("--structure", proc.stdout)
        self.assertNotIn("RuntimeWarning", proc.stderr)
        self.assertNotIn("found in sys.modules", proc.stderr)


if __name__ == "__main__":
    unittest.main()
