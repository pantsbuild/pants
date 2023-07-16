# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from pants_release.common import sorted_contributors


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate contributor list")
    parser.add_argument(
        "-s", "--since", help="Contributors since this revision, e.g. the Git tag `release_2.8.0`"
    )
    return parser


def main() -> None:
    args = create_parser().parse_args()
    if args.since:
        tag = args.since
        if not tag_exists(tag):
            tag = f"release_{tag}"
        print("  " + "\n  ".join(sorted_contributors(git_range=f"{tag}..HEAD")))
    else:
        update_contributors_md()


def update_contributors_md() -> None:
    Path("CONTRIBUTORS.md").write_text(
        "Created by running `./pants run build-support/bin/contributors.py`.\n\n+ "
        + "\n+ ".join(sorted_contributors(git_range="HEAD"))
        + "\n"
    )


def tag_exists(tag):
    return subprocess.run(["git", "rev-parse", tag + "^{tag}"], capture_output=True).returncode == 0


if __name__ == "__main__":
    main()
