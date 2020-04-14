# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for C++ (deprecated)."""

from pants.base.deprecated import _deprecated_contrib_plugin
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.cpp.rules.targets import CppBinary, CppLibrary
from pants.contrib.cpp.targets.cpp_binary import CppBinary as CppBinaryV1
from pants.contrib.cpp.targets.cpp_library import CppLibrary as CppLibraryV1
from pants.contrib.cpp.tasks.cpp_binary_create import CppBinaryCreate
from pants.contrib.cpp.tasks.cpp_compile import CppCompile
from pants.contrib.cpp.tasks.cpp_library_create import CppLibraryCreate
from pants.contrib.cpp.tasks.cpp_run import CppRun

_deprecated_contrib_plugin("pantsbuild.pants.contrib.cpp")


def build_file_aliases():
    return BuildFileAliases(targets={"cpp_library": CppLibraryV1, "cpp_binary": CppBinaryV1})


def register_goals():
    task(name="cpp", action=CppCompile).install("compile")
    task(name="cpplib", action=CppLibraryCreate).install("binary")
    task(name="cpp", action=CppBinaryCreate).install("binary")
    task(name="cpp", action=CppRun).install("run")


def targets2():
    return [CppBinary, CppLibrary]
