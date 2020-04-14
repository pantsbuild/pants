# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Python targets from Thrift.

See https://thrift.apache.org.
"""

from pants.backend.codegen.thrift.python.apache_thrift_py_gen import ApacheThriftPyGen
from pants.backend.codegen.thrift.python.py_thrift_namespace_clash_check import (
    PyThriftNamespaceClashCheck,
)
from pants.backend.codegen.thrift.python.python_thrift_library import (
    PythonThriftLibrary as PythonThriftLibraryV1,
)
from pants.backend.codegen.thrift.python.targets import PythonThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"python_thrift_library": PythonThriftLibraryV1})


def register_goals():
    task(name="thrift-py", action=ApacheThriftPyGen).install("gen")
    task(name="py-thrift-namespace-clash-check", action=PyThriftNamespaceClashCheck).install("gen")


def targets2():
    return [PythonThriftLibrary]
