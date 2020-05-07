#!/usr/bin/env python3
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import subprocess

from common import die


def main() -> None:
    globs = create_parser().parse_args().globs
    try:
        subprocess.run(
            [
                "./pants",
                # We run MyPy against targets with either the tag `type_checked` or `partially_type_checked`.
                # `partially_type_checked` means that the target is still missing type hints, but that we
                # still want to run MyPy against it so that we can enforce the type hints that may be there
                # already and we can make sure that we don't revert in adding code that MyPy flags as an
                # error.
                "--tag=+type_checked,partially_type_checked",
                "--tag=-nolint",
                "--backend-packages=pants.contrib.mypy",
                "--mypy-config=build-support/mypy/mypy.ini",
                "lint.mypy",
                "--include-requirements",
                *globs,
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        die("Please fix the above errors and run again.")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "globs",
        nargs="*",
        default=[
            "build-support::",
            "contrib::",
            "src/python::",
            "tests/python::",
            "pants-plugins::",
        ],
    )
    return parser


if __name__ == "__main__":
    main()
