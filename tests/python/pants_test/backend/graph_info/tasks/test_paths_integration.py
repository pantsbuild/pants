# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


# TODO: These tests duplicate the unit tests in `test_paths.py`, and should be removed in
# their favor. However, they also surface some errors which the unit tests don't -- see #6480.
class PathsIntegrationTest(PantsRunIntegrationTest):
    def test_paths_single(self):
        pants_run = self.run_pants(
            [
                "paths",
                "testprojects/src/python/python_targets:test_library_direct_dependee",
                "testprojects/src/python/python_targets:test_library",
            ]
        )
        self.assert_success(pants_run)
        self.assertIn("Found 1 path", pants_run.stdout_data)

    def test_paths_none(self):
        pants_run = self.run_pants(
            [
                "paths",
                "testprojects/src/python/python_targets:test_library",
                "testprojects/src/python/python_targets:test_library_direct_dependee",
            ]
        )
        self.assert_success(pants_run)
        self.assertIn("Found 0 paths", pants_run.stdout_data)
