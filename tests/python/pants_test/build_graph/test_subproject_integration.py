# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from textwrap import dedent

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.dirutil import safe_file_dump, safe_rmtree

SUBPROJ_SPEC = "testprojects/src/python/subproject_test/"
SUBPROJ_ROOT = "testprojects/src/python/subproject_test/subproject"


BUILD_FILES = {
    "testprojects/src/python/subproject_test/BUILD": """
      python_library(
        dependencies = ['//testprojects/src/python/subproject_test/subproject/src/python:helpers'],
      )
      """,
    "testprojects/src/python/subproject_test/subproject/BUILD": """
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
      """,
    "testprojects/src/python/subproject_test/subproject/src/python/BUILD": """
      python_library(
        name = 'helpers',
        dependencies = ['//src/python/helpershelpers'],
      )
      """,
    "testprojects/src/python/subproject_test/subproject/src/python/helpershelpers/BUILD": """
      python_library(
        name = 'helpershelpers',
      )
      """,
}


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


@contextmanager
def harness():
    try:
        for name, content in BUILD_FILES.items():
            safe_file_dump(name, dedent(content))
        yield
    finally:
        safe_rmtree(SUBPROJ_SPEC)


class SubprojectIntegrationTest(PantsRunIntegrationTest):
    def test_subproject_without_flag(self):
        """Assert that when getting the dependencies of a project which relies on a subproject which
        relies on its own internal library, a failure occurs without the --subproject-roots
        option."""
        with harness():
            pants_args = ["dependencies", SUBPROJ_SPEC]
            self.assert_failure(self.run_pants(pants_args))

    def test_subproject_with_flag(self):
        """Assert that when getting the dependencies of a project which relies on a subproject which
        relies on its own internal library, all things go well when that subproject is declared as a
        subproject."""
        with harness():
            # Has dependencies below the subproject.
            pants_args = [f"--subproject-roots={SUBPROJ_ROOT}", "dependencies", SUBPROJ_SPEC]
            self.assert_success(self.run_pants(pants_args))

            # A relative path at the root of the subproject.
            pants_args = [
                f"--subproject-roots={SUBPROJ_ROOT}",
                "dependencies",
                f"{SUBPROJ_ROOT}:local",
            ]
            self.assert_success(self.run_pants(pants_args))
