# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import tarfile

from pants_test.backend.python.pants_requirement_integration_test_base import (
    PantsRequirementIntegrationTestBase,
)


class SetupPyIntegrationTest(PantsRequirementIntegrationTestBase):
    def assert_sdist(self, pants_run, key, files):
        sdist_path = f"dist/{key}-0.0.1.tar.gz"
        self.assertTrue(re.search(r"Writing .*/{}".format(sdist_path), pants_run.stdout_data))

        src_entries = [f"src/{f}" for f in files]

        egg_info_entries = [
            f"src/{key.replace('-', '_')}.egg-info/{relpath}"
            for relpath in [
                "",
                "dependency_links.txt",
                "PKG-INFO",
                "requires.txt",
                "SOURCES.txt",
                "namespace_packages.txt",
                "top_level.txt",
            ]
        ]

        expected_entries = [
            f"{key}-0.0.1/{relpath}"
            for relpath in ["", "MANIFEST.in", "PKG-INFO", "setup.cfg", "setup.py", "src/"]
            + src_entries
            + egg_info_entries
        ]

        with tarfile.open(sdist_path, "r") as sdist:
            infos = sdist.getmembers()
            entries = [
                (info.name.rstrip("/") + "/" if info.isdir() else info.name) for info in infos
            ]
            self.assertEqual(
                sorted(expected_entries),
                sorted(entries),
                "\nExpected entries:\n{}\n\nActual entries:\n{}".format(
                    "\n".join(sorted(expected_entries)), "\n".join(sorted(entries))
                ),
            )

    def test_setup_py_unregistered_pants_plugin(self):
        """setup-py should succeed on a pants plugin target that:

        1. uses a pants_requirement() instead of linking directly to targets in the
           pants codebase.
        2. is not on the pythonpath nor registered as a backend package.
        """

        self.maxDiff = None

        with self.create_unstable_pants_distribution() as repo:
            command = [
                f"--python-repos-repos={repo}",
                "setup-py",
                "testprojects/pants-plugins/src/python/test_pants_plugin",
            ]
            pants_run = self.run_pants(command=command)
            self.assert_success(pants_run)

            self.assert_sdist(
                pants_run,
                "test_pants_plugin",
                [
                    "test_pants_plugin/",
                    "test_pants_plugin/__init__.py",
                    "test_pants_plugin/pants_testutil_tests.py",
                    "test_pants_plugin/register.py",
                    "test_pants_plugin/subsystems/",
                    "test_pants_plugin/subsystems/__init__.py",
                    "test_pants_plugin/subsystems/pants_testutil_subsystem.py",
                    "test_pants_plugin/subsystems/lifecycle_stubs.py",
                    "test_pants_plugin/tasks/",
                    "test_pants_plugin/tasks/__init__.py",
                    "test_pants_plugin/tasks/deprecation_warning_task.py",
                    "test_pants_plugin/tasks/lifecycle_stub_task.py",
                ],
            )
