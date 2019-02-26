# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

#from pants.contrib.rust.targets.original.cargo_binary import CargoBinary
#from pants.contrib.rust.targets.original.cargo_library import CargoLibrary
from pants.contrib.rust.targets.original.cargo_workspace import CargoWorkspace
from pants.contrib.rust.tasks.cargo_binary import Binary
from pants.contrib.rust.tasks.cargo_build import Build
from pants.contrib.rust.tasks.cargo_fetch import Fetch
from pants.contrib.rust.tasks.cargo_test import Test
from pants.contrib.rust.tasks.cargo_toolchain import Toolchain


def build_file_aliases():
  return BuildFileAliases(
    targets={
      #'cargo_binary': CargoBinary,
      #'cargo_library': CargoLibrary,
      'cargo_workspace': CargoWorkspace
    }
  )


def register_goals():
  task(name='cargo', action=Toolchain).install('bootstrap')
  task(name='cargo', action=Fetch).install('resolve')
  task(name='cargo', action=Build).install('compile')
  task(name='cargo', action=Binary).install('binary')
  task(name='cargo', action=Test).install('test')
