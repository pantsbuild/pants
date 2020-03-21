# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import OrderedDict

from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.backend.native.targets.native_library import CLibrary, CppLibrary
from pants.backend.native.tasks.c_compile import CCompile
from pants.backend.native.tasks.cpp_compile import CppCompile
from pants.backend.native.tasks.link_shared_libraries import LinkSharedLibraries
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.util.meta import classproperty
from pants_test.backend.python.tasks.util.build_local_dists_test_base import (
    BuildLocalPythonDistributionsTestBase,
)


class TestBuildLocalDistsWithCtypesNativeSources(BuildLocalPythonDistributionsTestBase):
    @classproperty
    def run_before_task_types(cls):
        return [CCompile, CppCompile, LinkSharedLibraries] + super().run_before_task_types

    dist_specs = OrderedDict(
        [
            (
                "src/python/plat_specific_c_dist:ctypes_c_library",
                {
                    "key": "ctypes_c_library",
                    "target_type": CLibrary,
                    "ctypes_native_library": NativeArtifact(lib_name="c-math-lib"),
                    "sources": ["c_math_lib.c", "c_math_lib.h"],
                    "filemap": {
                        "c_math_lib.c": """\
#include "c_math_lib.h"
int add_two(int x) { return x + 2; }
        """,
                        "c_math_lib.h": """\
int add_two(int);
        """,
                    },
                },
            ),
            (
                "src/python/plat_specific_c_dist:plat_specific_ctypes_c_dist",
                {
                    "key": "platform_specific_ctypes_c_dist",
                    "target_type": PythonDistribution,
                    "sources": ["__init__.py", "setup.py"],
                    "dependencies": ["src/python/plat_specific_c_dist:ctypes_c_library"],
                    "filemap": {
                        "__init__.py": "",
                        "setup.py": """\
from setuptools import setup, find_packages
setup(
  name='platform_specific_ctypes_c_dist',
  version='0.0.0',
  packages=find_packages(),
  data_files=[('', ['libc-math-lib.so'])],
)
        """,
                    },
                },
            ),
            (
                "src/python/plat_specific_cpp_dist:ctypes_cpp_library",
                {
                    "key": "ctypes_cpp_library",
                    "target_type": CppLibrary,
                    "ctypes_native_library": NativeArtifact(lib_name="cpp-math-lib"),
                    "sources": ["cpp_math_lib.cpp", "cpp_math_lib.hpp"],
                    "filemap": {
                        "cpp_math_lib.cpp": """\
#include "cpp_math_lib.hpp"
int add_two(int x) { return (x++) + 1; }
        """,
                        "cpp_math_lib.hpp": """\
int add_two(int);
        """,
                    },
                },
            ),
            (
                "src/python/plat_specific_cpp_dist:plat_specific_ctypes_cpp_dist",
                {
                    "key": "platform_specific_ctypes_cpp_dist",
                    "target_type": PythonDistribution,
                    "sources": ["__init__.py", "setup.py"],
                    "dependencies": ["src/python/plat_specific_cpp_dist:ctypes_cpp_library"],
                    "filemap": {
                        "__init__.py": "",
                        "setup.py": """\
from setuptools import setup, find_packages
setup(
  name='platform_specific_ctypes_cpp_dist',
  version='0.0.0',
  packages=find_packages(),
  data_files=[('', ['libcpp-math-lib.so'])],
)
        """,
                    },
                },
            ),
        ]
    )

    def test_ctypes_c_dist(self):
        platform_specific_dist = self.target_dict["platform_specific_ctypes_c_dist"]
        self._assert_dist_and_wheel_identity(
            expected_name="platform_specific_ctypes_c_dist",
            expected_version="0.0.0",
            expected_platform=self.ExpectedPlatformType.current,
            dist_target=platform_specific_dist,
            extra_targets=[self.target_dict["ctypes_c_library"]],
        )

    def test_ctypes_cpp_dist(self):
        platform_specific_dist = self.target_dict["platform_specific_ctypes_cpp_dist"]
        self._assert_dist_and_wheel_identity(
            expected_name="platform_specific_ctypes_cpp_dist",
            expected_version="0.0.0",
            expected_platform=self.ExpectedPlatformType.current,
            dist_target=platform_specific_dist,
            extra_targets=[self.target_dict["ctypes_cpp_library"]],
        )

    def test_multiplatform_python_setup_resolve_bypasses_python_setup(self):
        self.set_options_for_scope(
            "python-setup", platforms=["current", "linux-x86_64", "macosx_10_14_x86_64"]
        )
        platform_specific_dist = self.target_dict["platform_specific_ctypes_cpp_dist"]
        self._assert_dist_and_wheel_identity(
            expected_name="platform_specific_ctypes_cpp_dist",
            expected_version="0.0.0",
            expected_platform=self.ExpectedPlatformType.current,
            dist_target=platform_specific_dist,
            extra_targets=[self.target_dict["ctypes_cpp_library"]],
        )

    def test_resolve_for_native_sources_allows_current_platform_only(self):
        platform_specific_dist = self.target_dict["platform_specific_ctypes_cpp_dist"]
        compatible_python_binary_target = self.make_target(
            spec="src/python/plat_specific:bin",
            target_type=PythonBinary,
            dependencies=[platform_specific_dist],
            entry_point="this-will-not-run",
            platforms=["current"],
        )
        self._assert_dist_and_wheel_identity(
            expected_name="platform_specific_ctypes_cpp_dist",
            expected_version="0.0.0",
            expected_platform=self.ExpectedPlatformType.current,
            dist_target=platform_specific_dist,
            extra_targets=[
                self.target_dict["ctypes_cpp_library"],
                compatible_python_binary_target,
            ],
        )
