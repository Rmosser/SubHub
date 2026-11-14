#!/usr/bin/env python3
"""Stage package documentation without local third-party reference checkouts."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    shutil.copytree(
        args.source,
        args.destination,
        ignore=shutil.ignore_patterns("参考项目"),
    )


if __name__ == "__main__":
    main()
