# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.project_info.tasks.dependencies import Dependencies
from pants.backend.project_info.tasks.depmap import Depmap
from pants.backend.project_info.tasks.eclipse_gen import EclipseGen
from pants.backend.project_info.tasks.ensime_gen import EnsimeGen
from pants.backend.project_info.tasks.export import Export
from pants.backend.project_info.tasks.filedeps import FileDeps
from pants.backend.project_info.tasks.idea_gen import IdeaGen
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  pass


# TODO https://github.com/pantsbuild/pants/issues/604 register_goals
def register_goals():
  # IDE support.
  task(name='idea', action=IdeaGen).install()
  task(name='eclipse', action=EclipseGen).install()
  task(name='ensime', action=EnsimeGen).install()
  task(name='export', action=Export).install()

  task(name='depmap', action=Depmap).install()
  task(name='dependencies', action=Dependencies).install()
  task(name='filedeps', action=FileDeps).install('filedeps')
