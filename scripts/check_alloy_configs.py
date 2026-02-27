#!/usr/bin/env python3
"""Validate Alloy config files by parsing them with `alloy fmt`."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def collect_alloy_files(paths):
    files = []
    for entry in paths:
        path = Path(entry)
        if path.is_file() and path.suffix == ".alloy":
            files.append(path)
            continue
        if path.is_dir():
            files.extend(path.rglob("*.alloy"))
    return sorted(files, key=lambda p: p.as_posix().lower())


def main():
    parser = argparse.ArgumentParser(
        description="Validate Alloy files by parsing with `alloy fmt`."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["generated.example"],
        help="File and/or directory paths to validate",
    )
    args = parser.parse_args()

    alloy_bin = shutil.which("alloy")
    if not alloy_bin:
        print("Error: `alloy` executable not found in PATH.", file=sys.stderr)
        return 1

    alloy_files = collect_alloy_files(args.paths)
    if not alloy_files:
        print("Error: no .alloy files found in the provided paths.", file=sys.stderr)
        return 1

    failures = []
    for file_path in alloy_files:
        result = subprocess.run(
            [alloy_bin, "fmt", str(file_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip()
            failures.append((file_path, output))

    if failures:
        print("Alloy validation failed:", file=sys.stderr)
        for file_path, output in failures:
            print(f"  - {file_path}", file=sys.stderr)
            if output:
                print(f"    {output}", file=sys.stderr)
        return 1

    print(f"Validated {len(alloy_files)} Alloy file(s) with `alloy fmt`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
