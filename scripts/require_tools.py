#!/usr/bin/env python3
"""Require external CLI tools to be available in PATH."""

import shutil
import sys


INSTALL_HINTS = {
    "actionlint": "https://github.com/rhysd/actionlint",
    "act": "https://github.com/nektos/act",
}


def main():
    tools = sys.argv[1:]
    if not tools:
        print("Usage: require_tools.py <tool> [<tool> ...]", file=sys.stderr)
        return 2

    missing = [tool for tool in tools if shutil.which(tool) is None]
    if not missing:
        return 0

    print("Missing required tool(s):", ", ".join(missing), file=sys.stderr)
    for tool in missing:
        hint = INSTALL_HINTS.get(tool)
        if hint:
            print(f"  - {tool}: install instructions: {hint}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
