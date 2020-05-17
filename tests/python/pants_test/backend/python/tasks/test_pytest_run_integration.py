# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.testutil.interpreter_selection_utils import (
    PY_3,
    PY_27,
    python_interpreter_path,
    skip_unless_python3_present,
    skip_unless_python27_and_python3_present,
    skip_unless_python27_present,
)
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.testutil.pexrc_util import setup_pexrc_with_pex_python_path
from pants.util.contextutil import temporary_dir


class PytestRunIntegrationTest(PantsRunIntegrationTest):
    testproject = "testprojects/src/python/interpreter_selection"

    # NB: Occasionally running a test in CI may take multiple seconds. The tests in this file which
    # use the --timeout-default argument are not testing for performance regressions, but just for
    # correctness of timeout behavior, so we set this to a higher value to avoid flakiness.
    _non_flaky_timeout_seconds = 5

    pytest_setup_for_python_2_tests = {
        "pytest": {
            "version": "pytest==4.6.6",  # so that we can run Python 2 tests
            "pytest_plugins": ["zipp==1.0.0"],  # transitive dep of Pytest
        }
    }

    def test_pytest_run_conftest_succeeds(self):
        pants_run = self.run_pants(["test.pytest", "testprojects/tests/python/pants/conf_test"])
        self.assert_success(pants_run)

    def test_pytest_explicit_coverage(self):
        with temporary_dir() as coverage_dir:
            pants_run = self.run_pants(
                [
                    "test.pytest",
                    "--coverage=pants.constants_only",
                    f"--test-pytest-coverage-output-dir={coverage_dir}",
                    "testprojects/tests/python/pants/constants_only",
                ]
            )
            self.assert_success(pants_run)
            self.assertTrue(os.path.exists(os.path.join(coverage_dir, "coverage.xml")))

    def test_pytest_with_profile(self):
        with temporary_dir() as profile_dir:
            prof = os.path.join(profile_dir, "pants.prof")
            pants_run = self.run_pants(
                ["test.pytest", "testprojects/tests/python/pants/constants_only:constants_only",],
                extra_env={"PANTS_PROFILE": prof},
            )
            self.assert_success(pants_run)
            # Note that the subprocess profile mechanism will add a ".0" to the profile path.
            # We won't see a profile at prof itself because PANTS_PROFILE wasn't set when the
            # current process started.
            self.assertTrue(os.path.exists(f"{prof}.0"))

    @skip_unless_python27_and_python3_present
    def test_pants_test_interpreter_selection_with_pexrc(self):
        """Test the pants test goal with interpreters selected from a PEX_PYTHON_PATH defined in a
        pexrc file on disk."""
        py27_path, py3_path = python_interpreter_path(PY_27), python_interpreter_path(PY_3)
        with setup_pexrc_with_pex_python_path([py27_path, py3_path]):
            with temporary_dir() as interpreters_cache:
                pants_ini_config = {
                    "python-setup": {
                        "interpreter_cache_dir": interpreters_cache,
                        "interpreter_search_paths": ["<PEXRC>"],
                    },
                    **self.pytest_setup_for_python_2_tests,
                }
                pants_run_27 = self.run_pants(
                    command=[
                        "test",
                        "{}:test_py2".format(
                            os.path.join(self.testproject, "python_3_selection_testing")
                        ),
                    ],
                    config=pants_ini_config,
                )
                self.assert_success(pants_run_27)
                pants_run_3 = self.run_pants(
                    command=[
                        "test",
                        "{}:test_py3".format(
                            os.path.join(self.testproject, "python_3_selection_testing")
                        ),
                    ],
                    config=pants_ini_config,
                )
                self.assert_success(pants_run_3)

    @skip_unless_python27_present
    def test_pants_test_interpreter_selection_with_option_2(self):
        """Test that the pants test goal properly constrains the SelectInterpreter task to Python 2
        using the '--python-setup-interpreter-constraints' option."""
        with temporary_dir() as interpreters_cache:
            pants_ini_config = {
                "python-setup": {
                    "interpreter_constraints": ["CPython>=2.7"],
                    "interpreter_cache_dir": interpreters_cache,
                },
                **self.pytest_setup_for_python_2_tests,
            }
            pants_run_2 = self.run_pants(
                command=[
                    "test",
                    f"{os.path.join(self.testproject, 'python_3_selection_testing')}:test_py2",
                    '--python-setup-interpreter-constraints=["CPython<3"]',
                ],
                config=pants_ini_config,
            )
            self.assert_success(pants_run_2)

    @skip_unless_python3_present
    def test_pants_test_interpreter_selection_with_option_3(self):
        """Test that the pants test goal properly constrains the SelectInterpreter task to Python 3
        using the '--python-setup-interpreter-constraints' option."""
        with temporary_dir() as interpreters_cache:
            pants_ini_config = {
                "python-setup": {
                    "interpreter_constraints": ["CPython>=2.7"],
                    "interpreter_cache_dir": interpreters_cache,
                }
            }
            pants_run_3 = self.run_pants(
                command=[
                    "test",
                    f"{os.path.join(self.testproject, 'python_3_selection_testing')}:test_py3",
                    '--python-setup-interpreter-constraints=["CPython>=3.6"]',
                ],
                config=pants_ini_config,
            )
            self.assert_success(pants_run_3)
