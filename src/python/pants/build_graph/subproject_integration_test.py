# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from textwrap import dedent
from typing import Iterator

from pants.testutil.pants_integration_test import run_pants
from pants.util.dirutil import safe_file_dump, safe_rmtree

"""
Test layout
-----------
testprojects/
  src/
    python/
      subproject_test/
        BUILD
        subproject/
          src/
            python/
              BUILD/
              helpershelpers/
                BUILD/
"""

SUBPROJ_SPEC = "testprojects/src/python/subproject_test"
SUBPROJ_ROOT = "testprojects/src/python/subproject_test/subproject"


BUILD_FILES = {
    f"{SUBPROJ_SPEC}/a.py": "",
    f"{SUBPROJ_SPEC}/BUILD": (
        f"python_sources(dependencies = ['{SUBPROJ_ROOT}/src/python:helpers'])"
    ),
    f"{SUBPROJ_ROOT}/src/python/a.py": "",
    f"{SUBPROJ_ROOT}/src/python/BUILD": dedent(
        """
        python_sources(
            name = 'helpers',
            dependencies = ['src/python/helpershelpers'],
        )
      """
    ),
    f"{SUBPROJ_ROOT}/src/python/helpershelpers/a.py": "",
    f"{SUBPROJ_ROOT}/src/python/helpershelpers/BUILD": "python_sources()",
    f"{SUBPROJ_ROOT}/BUILD": dedent(
        """\
        target(
            name = 'local',
            dependencies = [
                ':relative',
                '//:absolute',
            ],
        )

        target(
            name = 'relative',
        )

        target(
            name = 'absolute',
        )
        """
    ),
}


@contextmanager
def harness() -> Iterator[None]:
    try:
        for name, content in BUILD_FILES.items():
            safe_file_dump(name, content)
        yield
    finally:
        safe_rmtree(SUBPROJ_SPEC)


def test_subproject() -> None:
    with harness():
        # If `--subproject-roots` are not specified, we expect a failure.
        run_pants(
            [
                "--backend-packages=pants.backend.python",
                "dependencies",
                "--transitive",
                SUBPROJ_SPEC,
            ]
        ).assert_failure()

        # The same command should succeed when `--subproject-roots` are specified.
        run_pants(
            [
                "--backend-packages=pants.backend.python",
                f"--subproject-roots={SUBPROJ_ROOT}",
                "dependencies",
                "--transitive",
                SUBPROJ_SPEC,
            ]
        ).assert_success()

        # Both relative and absolute dependencies should work.
        run_pants(
            [
                "--backend-packages=pants.backend.python",
                f"--subproject-roots={SUBPROJ_ROOT}",
                "dependencies",
                f"{SUBPROJ_ROOT}:local",
            ]
        ).assert_success()
