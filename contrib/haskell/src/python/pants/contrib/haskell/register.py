# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar

from pants.contrib.haskell.targets.haskell_hackage_package import HaskellHackagePackage
from pants.contrib.haskell.targets.haskell_project import HaskellProject
from pants.contrib.haskell.targets.haskell_source_package import HaskellSourcePackage
from pants.contrib.haskell.targets.haskell_stackage_package import HaskellStackagePackage
from pants.contrib.haskell.tasks.stack_build import StackBuild


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'haskell_hackage_package': HaskellHackagePackage,
      'haskell_stackage_package': HaskellStackagePackage,
      'haskell_source_package': HaskellSourcePackage,
      'haskell_project': HaskellProject,
    }
  )


def register_goals():
  TaskRegistrar(name='stack-build', action=StackBuild).install('compile')
