# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.build_environment import get_buildroot
from pants_test.backend.python.pants_requirement_integration_test_base import (
    PantsRequirementIntegrationTestBase,
)


class PantsRequirementIntegrationTest(PantsRequirementIntegrationTestBase):
    """A pants plugin should be able to depend on a pants_requirement() alone to declare its
    dependencies on pants modules.

    This plugin, when added to the pythonpath and backend_packages, should be able to declare new
    BUILD file objects.
    """

    @classmethod
    def use_pantsd_env_var(cls):
        """The test fails to run under pantsd because of a failure to initialize a subsystem."""
        return False

    def run_with_testproject_backend_pkgs(self, cmd):
        testproject_backend_src_dir = os.path.join(
            get_buildroot(), "testprojects/pants-plugins/src/python"
        )
        testproject_backend_pkg_name = "test_pants_plugin"
        pants_req_addr = "testprojects/pants-plugins/3rdparty/python/pants"
        pants_testutil_addr = "src/python/pants/testutil:testutil_wheel"
        pre_cmd_args = [
            f"--pythonpath=+['{testproject_backend_src_dir}']",
            f"--backend-packages=+['{testproject_backend_pkg_name}']",
            f"--pants-testutil-requirement-target={pants_req_addr}",
            f"--pants-testutil-testutil-target={pants_testutil_addr}",
        ]
        command = pre_cmd_args + cmd
        return self.run_pants(command=command)

    def test_pants_requirement(self):
        self.maxDiff = None

        with self.create_unstable_pants_distribution() as repo:
            tests_dir = "testprojects/pants-plugins/tests/python/test_pants_plugin"
            with self.file_renamed(os.path.join(get_buildroot(), tests_dir), "TEST_BUILD", "BUILD"):
                test_pants_requirement_cmd = [f"--python-repos-repos={repo}", "test", tests_dir]
                pants_run = self.run_with_testproject_backend_pkgs(test_pants_requirement_cmd)
                self.assert_success(pants_run)
