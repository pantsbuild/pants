# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from textwrap import dedent
from typing import Iterator

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
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
    f"{SUBPROJ_SPEC}/BUILD": (
        f"python_library(dependencies = ['{SUBPROJ_ROOT}/src/python:helpers'])"
    ),
    f"{SUBPROJ_ROOT}/src/python/BUILD": dedent(
        """
        python_library(
            name = 'helpers',
            dependencies = ['src/python/helpershelpers'],
        )
      """
    ),
    f"{SUBPROJ_ROOT}/src/python/helpershelpers/BUILD": "python_library()",
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


class SubprojectIntegrationTest(PantsRunIntegrationTest):
    def test_subproject(self) -> None:
        with harness():
            # If `--subproject-roots` are not specified, we expect a failure.
            self.assert_failure(self.run_pants(["dependencies", "--transitive", SUBPROJ_SPEC]))

            # The same command should succeed when `--subproject-roots` are specified.
            self.assert_success(
                self.run_pants(
                    [
                        f"--subproject-roots={SUBPROJ_ROOT}",
                        "dependencies",
                        "--transitive",
                        SUBPROJ_SPEC,
                    ]
                )
            )

            # Both relative and absolute dependencies should work.
            self.assert_success(
                self.run_pants(
                    [f"--subproject-roots={SUBPROJ_ROOT}", "dependencies", f"{SUBPROJ_ROOT}:local"]
                )
            )
