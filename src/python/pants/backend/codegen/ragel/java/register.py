# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Java targets from Ragel finite state machines.

See http://www.colm.net/open-source/ragel/.
"""

from pants.backend.codegen.ragel.java.java_ragel_library import (
    JavaRagelLibrary as JavaRagelLibraryV1,
)
from pants.backend.codegen.ragel.java.ragel_gen import RagelGen
from pants.backend.codegen.ragel.java.targets import JavaRagelLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"java_ragel_library": JavaRagelLibraryV1})


def register_goals():
    task(name="ragel", action=RagelGen).install("gen")


def targets2():
    return [JavaRagelLibrary]
