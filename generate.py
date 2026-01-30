#!/usr/bin/env python3
"""Convenience wrapper for common generation workflows."""

from __future__ import annotations

import argparse
import sys

from alloy_config_generator.cli import main as cli_main


def build_example_args(args: argparse.Namespace) -> list[str]:
    """Build CLI args for deterministic example generation."""
    output_dir = args.example_output_dir
    return [
        "--all",
        "--definitions-dir",
        "definitions.example",
        "--output-dir",
        output_dir,
        "--format",
        args.example_format,
        "--no-manifest",
        "--clean",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Alloy configs from definitions.")
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Generate example outputs from definitions.example into generated.example.",
    )
    parser.add_argument(
        "--example-output-dir",
        default="generated.example",
        help="Output directory for example generation.",
    )
    parser.add_argument(
        "--example-format",
        default="both",
        choices=["alloy", "configmap", "both", "argocd", "all"],
        help="Output format to generate when using --examples.",
    )
    parser.add_argument(
        "cli_args",
        nargs=argparse.REMAINDER,
        help="Arguments to pass through to the underlying CLI.",
    )
    args = parser.parse_args()

    if args.examples:
        sys.argv = [sys.argv[0], *build_example_args(args)]
        cli_main()
        return

    if args.cli_args:
        sys.argv = [sys.argv[0], *args.cli_args]
    cli_main()


if __name__ == "__main__":
    main()
