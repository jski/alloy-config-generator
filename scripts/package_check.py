#!/usr/bin/env python3
"""Smoke-test the built wheel in a temporary virtual environment."""

import subprocess
import sys
import tempfile
import venv
import os
from pathlib import Path


def newest_wheel(dist_dir):
    wheels = list(Path(dist_dir).glob("*.whl"))
    if not wheels:
        print(f"Error: no wheel files found in {dist_dir}", file=sys.stderr)
        return None
    return max(wheels, key=lambda p: p.stat().st_mtime)


def run_command(command):
    result = subprocess.run(command)
    return result.returncode


def venv_paths(venv_dir):
    if os.name == "nt":
        scripts_dir = venv_dir / "Scripts"
        return scripts_dir / "python.exe", scripts_dir / "alloygen.exe"
    bin_dir = venv_dir / "bin"
    return bin_dir / "python", bin_dir / "alloygen"


def main():
    wheel = newest_wheel("dist")
    if wheel is None:
        return 1

    print(f"Using wheel: {wheel}")
    with tempfile.TemporaryDirectory(prefix="alloygen-package-check-") as temp_dir:
        venv_dir = Path(temp_dir) / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python_bin, alloygen_bin = venv_paths(venv_dir)

        commands = [
            [str(python_bin), "-m", "pip", "install", str(wheel)],
            [str(alloygen_bin), "--version"],
            [str(alloygen_bin), "--help"],
        ]
        for command in commands:
            code = run_command(command)
            if code != 0:
                return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
