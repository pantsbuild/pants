# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Python targets from Antlr3 and Antlr4.

See https://www.antlr.org.
"""

from pants.backend.codegen.antlr.python.antlr_py_gen import AntlrPyGen
from pants.backend.codegen.antlr.python.python_antlr_library import (
    PythonAntlrLibrary as PythonAntlrLibraryV1,
)
from pants.backend.codegen.antlr.python.targets import PythonAntlrLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(targets={"python_antlr_library": PythonAntlrLibraryV1})


def register_goals():
    task(name="antlr-py", action=AntlrPyGen).install("gen")


def targets2():
    return [PythonAntlrLibrary]
