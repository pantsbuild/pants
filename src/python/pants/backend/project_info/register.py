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
  task(name='idea', action=IdeaGen).install().with_description(
      'Create an IntelliJ IDEA project from the given targets.')

  task(name='eclipse', action=EclipseGen).install().with_description(
      'Create an Eclipse project from the given targets.')

  task(name='ensime', action=EnsimeGen).install().with_description(
      'Create an Ensime project from the given targets.')

  task(name='export', action=Export).install().with_description(
    'Export project information for targets in JSON format. '
    'Use with resolve goal to get detailed information about libraries.')

  task(name='depmap', action=Depmap).install().with_description("Depict the target's dependencies.")

  task(name='dependencies', action=Dependencies).install().with_description(
      "Print the target's dependencies.")

  task(name='filedeps', action=FileDeps).install('filedeps').with_description(
      'Print out the source and BUILD files the target depends on.')
