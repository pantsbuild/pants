# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.utils.parse_search_dirs import ParseSearchDirs
from pants.engine.platform import Platform
from pants.testutil.subsystem.util import global_subsystem_instance, init_subsystems
from pants.testutil.test_base import TestBase
from pants_test.backend.native.util.platform_utils import platform_specific


class TestLibcDirectorySearchFailure(TestBase):
    def setUp(self):
        init_subsystems(
            [LibcDev],
            options={"libc": {"enable_libc_search": True, "libc_dir": "/does/not/exist"}},
        )

        self.libc = global_subsystem_instance(LibcDev)
        self.platform = Platform.current

    def test_libc_search_failure(self):
        with self.assertRaises(LibcDev.HostLibcDevResolutionError) as cm:
            self.libc.get_libc_objects()
        expected_msg = "Could not locate crti.o in directory /does/not/exist provided by the --libc-dir option."
        self.assertEqual(expected_msg, str(cm.exception))


class TestLibcSearchDisabled(TestBase):
    def setUp(self):
        init_subsystems(
            [LibcDev],
            options={"libc": {"enable_libc_search": False, "libc_dir": "/does/not/exist"}},
        )

        self.libc = global_subsystem_instance(LibcDev)
        self.platform = Platform.current

    def test_libc_disabled_search(self):
        self.assertEqual([], self.libc.get_libc_objects())


class TestLibcCompilerSearchFailure(TestBase):
    def setUp(self):
        init_subsystems(
            [LibcDev],
            options={
                "libc": {
                    "enable_libc_search": True,
                    "host_compiler": "this_executable_does_not_exist",
                },
            },
        )

        self.libc = global_subsystem_instance(LibcDev)
        self.platform = Platform.current

    @platform_specific("linux")
    def test_libc_compiler_search_failure(self):
        with self.assertRaises(ParseSearchDirs.ParseSearchDirsError) as cm:
            self.libc.get_libc_objects()
        expected_msg = (
            "Process invocation with argv "
            "'this_executable_does_not_exist -print-search-dirs' and environment None failed."
        )
        self.assertIn(expected_msg, str(cm.exception))
