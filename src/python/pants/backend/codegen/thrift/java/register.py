# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.java.apache_thrift_java_gen import ApacheThriftJavaGen
from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'java_thrift_library': JavaThriftLibrary,
      }
    )


def register_goals():
  task(name='thrift-java', action=ApacheThriftJavaGen).install('gen')
