# SPDX-License-Identifier: Apache-2.0
"""Command line entry point."""
import argparse
import sys

from patchtrail import __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="patchtrail")
    ap.add_argument("--version", action="store_true", help="print version and exit")
    args = ap.parse_args(argv)
    if args.version:
        print(f"patchtrail {__version__}")
    return 0


def run() -> None:
    sys.exit(main())
