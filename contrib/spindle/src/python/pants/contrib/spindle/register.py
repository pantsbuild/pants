# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.spindle.targets.spindle_thrift_library import SpindleThriftLibrary
from pants.contrib.spindle.tasks.spindle_gen import SpindleGen


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'spindle_thrift_library': SpindleThriftLibrary,
    }
  )


def register_goals():
  task(name='spindle', action=SpindleGen).install('gen')
