#!/usr/bin/env python3
"""Local version-bump guard mirroring CI logic."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib


RELEASE_PATHS = [
    "alloy_config_generator/**",
    "templates/**",
    "generate.py",
    "pyproject.toml",
    "definitions.example/**",
]


def git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def version_from_ref(git_ref: str) -> str:
    data = git_output("show", f"{git_ref}:pyproject.toml")
    parsed = tomllib.loads(data)
    return parsed["project"]["version"]


def resolve_base_sha(base_ref: str) -> str:
    return git_output("merge-base", "HEAD", base_ref)


def release_paths_changed(base_sha: str, head_sha: str) -> bool:
    cmd = ["diff", "--name-only", base_sha, head_sha, "--", *RELEASE_PATHS]
    changed = git_output(*cmd)
    return bool(changed)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail if release-worthy changes lack a version bump."
    )
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Git ref to compare HEAD against (default: origin/main).",
    )
    args = parser.parse_args()

    try:
        base_sha = resolve_base_sha(args.base_ref)
    except subprocess.CalledProcessError:
        print(
            f"Warning: Could not resolve base ref '{args.base_ref}'. Skipping version check."
        )
        return 0

    head_sha = git_output("rev-parse", "HEAD")

    if not release_paths_changed(base_sha, head_sha):
        print("Version guard: no release-worthy changes detected.")
        return 0

    base_version = version_from_ref(base_sha)
    head_version = version_from_ref(head_sha)
    if base_version == head_version:
        print("Release-worthy changes detected but project.version did not change.")
        print(f"Base: {base_version}")
        print(f"Head: {head_version}")
        print("Please bump project.version in pyproject.toml.")
        return 1

    print(f"Version guard: project.version changed ({base_version} -> {head_version}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
