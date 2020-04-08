# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Java targets from Java Architecture for XML Bindings (JAXB).

See https://www.oracle.com/technical-resources/articles/javase/jaxb.html.
"""

from pants.backend.codegen.jaxb.jaxb_gen import JaxbGen
from pants.backend.codegen.jaxb.jaxb_library import JaxbLibrary as JaxbLibraryV1
from pants.backend.codegen.jaxb.targets import JaxbLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"jaxb_library": JaxbLibraryV1})


def register_goals():
    task(name="jaxb", action=JaxbGen).install("gen")


def targets2():
    return [JaxbLibrary]
