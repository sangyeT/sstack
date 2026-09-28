#!/usr/bin/env python3
"""Run SStack lint and contract checks; never fixes or changes source files."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "tools/sstack"


def main():
    missing = [name for name in ("ruff", "yaml") if importlib.util.find_spec(name) is None]
    if missing:
        print("Missing lint dependencies. Install with the same Python interpreter:")
        print(f"{sys.executable} -m pip install -r {STACK / 'requirements-dev.txt'}")
        return 1
    checks = [
        [sys.executable, "-m", "ruff", "check", "--config", str(STACK / "ruff.toml"), str(STACK)],
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "--config",
            str(STACK / "ruff.toml"),
            str(STACK),
        ],
        [sys.executable, str(STACK / "check_contracts.py")],
    ]
    failed = False
    for command in checks:
        try:
            result = subprocess.run(command, cwd=ROOT, timeout=120, check=False)
            failed = result.returncode != 0 or failed
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"Lint check unavailable: {type(error).__name__}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
