# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Java targets from Protocol Buffers (Protobufs).

See https://developers.google.com/protocol-buffers/.
"""

from pants.backend.codegen.protobuf.java.java_protobuf_library import (
    JavaProtobufLibrary as JavaProtobufLibraryV1,
)
from pants.backend.codegen.protobuf.java.protobuf_gen import ProtobufGen
from pants.backend.codegen.protobuf.java.targets import JavaProtobufLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"java_protobuf_library": JavaProtobufLibraryV1})


def register_goals():
    task(name="protoc", action=ProtobufGen).install("gen")


def targets2():
    return [JavaProtobufLibrary]
