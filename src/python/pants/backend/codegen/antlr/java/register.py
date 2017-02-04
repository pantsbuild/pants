# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.antlr.java.antlr_java_gen import AntlrJavaGen
from pants.backend.codegen.antlr.java.java_antlr_library import JavaAntlrLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'java_antlr_library': JavaAntlrLibrary,
    }
  )


def register_goals():
  task(name='antlr-java', action=AntlrJavaGen).install('gen')
