# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Java targets from Antlr3 and Antlr4.

See https://www.antlr.org.
"""

from pants.backend.codegen.antlr.java.antlr_java_gen import AntlrJavaGen
from pants.backend.codegen.antlr.java.java_antlr_library import (
    JavaAntlrLibrary as JavaAntlrLibraryV1,
)
from pants.backend.codegen.antlr.java.targets import JavaAntlrLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"java_antlr_library": JavaAntlrLibraryV1})


def register_goals():
    task(name="antlr-java", action=AntlrJavaGen).install("gen")


def targets2():
    return [JavaAntlrLibrary]
