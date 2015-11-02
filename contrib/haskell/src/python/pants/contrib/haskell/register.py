# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar

from pants.contrib.haskell.targets.cabal import Cabal
from pants.contrib.haskell.targets.hackage import Hackage
from pants.contrib.haskell.targets.stackage import Stackage
from pants.contrib.haskell.tasks.stack_build import StackBuild


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'stackage': Stackage,
    }
  )

def register_goals():
  TaskRegistrar(name='stack-build', action=StackBuild).install('compile')
