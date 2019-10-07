# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.java.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.protobuf.java.protobuf_gen import ProtobufGen
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'java_protobuf_library': JavaProtobufLibrary,
    }
  )


def register_goals():
  task(name='protoc', action=ProtobufGen).install('gen')
