#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from pathlib import Path

from common import die

DIRS_TO_CHECK = (
    "src/python",
    "tests/python",
    "pants-plugins",
    "build-support/bin",
    "build-support/migration-support",
)


def main() -> None:
    exclude_check = {
        "src/python/pants/__init__.py",
        "src/python/pants/testutil/__init__.py",
    }
    files = itertools.chain.from_iterable(
        [Path().glob(f"{d}/**/__init__.py") for d in DIRS_TO_CHECK]
    )
    non_empty_inits = {str(f) for f in files if bool(f.read_text())}
    if non_empty_inits - exclude_check:
        die(
            "All `__init__.py` file should be empty, but the following had content: "
            f"{', '.join(f for f in non_empty_inits)}"
        )


if __name__ == "__main__":
    main()
