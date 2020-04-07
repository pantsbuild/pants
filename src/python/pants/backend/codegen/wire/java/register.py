# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Java targets from the Wire protocol."""

from pants.backend.codegen.wire.java.java_wire_library import JavaWireLibrary as JavaWireLibraryV1
from pants.backend.codegen.wire.java.targets import JavaWireLibrary
from pants.backend.codegen.wire.java.wire_gen import WireGen
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"java_wire_library": JavaWireLibraryV1})


def register_goals():
    task(name="wire", action=WireGen).install("gen")


def targets2():
    return [JavaWireLibrary]
