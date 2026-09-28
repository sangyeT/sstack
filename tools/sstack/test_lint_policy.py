import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LintPolicyTests(unittest.TestCase):
    def lint(self, source):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.py"
            path.write_text(source)
            config = Path(__file__).with_name("ruff.toml")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "--no-cache",
                    "--config",
                    str(config),
                    "--output-format",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertIn(result.returncode, (0, 1), result.stderr)
            return {item["code"] for item in json.loads(result.stdout)}

    def test_rejects_hidden_failure_and_mutable_default(self):
        codes = self.lint(
            "def read(items=[]):\n    try:\n        return missing\n    except Exception:\n        return []\n"
        )
        self.assertTrue({"B006", "F821", "BLE001"} <= codes, codes)

    def test_accepts_explicit_boundary_failure(self):
        self.assertEqual(
            self.lint(
                'def parse(value):\n    try:\n        return int(value)\n    except ValueError as error:\n        raise ValueError("Expected an integer") from error\n'
            ),
            set(),
        )
