# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Java targets from Thrift.

See https://thrift.apache.org.
"""

from pants.backend.codegen.thrift.java.apache_thrift_java_gen import ApacheThriftJavaGen
from pants.backend.codegen.thrift.java.java_thrift_library import (
    JavaThriftLibrary as JavaThriftLibraryV1,
)
from pants.backend.codegen.thrift.java.targets import JavaThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"java_thrift_library": JavaThriftLibraryV1})


def register_goals():
    task(name="thrift-java", action=ApacheThriftJavaGen).install("gen")


def targets2():
    return [JavaThriftLibrary]
