#!/usr/bin/env python3
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from pathlib import Path

from common import die

DIRS_TO_CHECK = (
    "src",
    "tests",
    "pants-plugins",
    "examples",
    "build-support/bin",
    "build-support/migration-support",
)


def main() -> None:
    files = itertools.chain.from_iterable(
        [Path().glob(f"{d}/**/__init__.py") for d in DIRS_TO_CHECK]
    )
    root_init = Path("src/python/pants/__init__.py")
    if '__import__("pkg_resources").declare_namespace(__name__)' not in root_init.read_text():
        die(
            f"{root_init} must have the line "
            '`__import__("pkg_resources").declare_namespace(__name__)` in it.'
        )
    non_empty_inits = [f for f in files if bool(f.read_text()) and f != root_init]
    if non_empty_inits:
        die(
            "All `__init__.py` file should be empty, but the following had content: "
            f"{', '.join(str(f) for f in non_empty_inits)}"
        )


if __name__ == "__main__":
    main()
