# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate contributor list")
    parser.add_argument(
        "-s", "--since", help="Contributors since this revision, e.g. the Git tag `release_2.8.0`"
    )
    return parser


def main() -> None:
    args = create_parser().parse_args()
    if args.since:
        print("  " + "\n  ".join(sorted_contributors(range=f"{args.since}..HEAD")))
    else:
        update_contributors_md()


def sorted_contributors(range: str) -> list[str]:
    contributors = set(
        subprocess.run(
            ["git", "log", "--use-mailmap", "--format=format:%aN", range],
            stdout=subprocess.PIPE,
            check=True,
        )
        .stdout.decode()
        .splitlines()
    )
    return sorted(contributors)


def update_contributors_md() -> None:
    Path("CONTRIBUTORS.md").write_text(
        "Created by running `./pants run build-support/bin/contributors.py`.\n\n+ "
        + "\n+ ".join(sorted_contributors(range="HEAD"))
        + "\n"
    )


if __name__ == "__main__":
    main()
