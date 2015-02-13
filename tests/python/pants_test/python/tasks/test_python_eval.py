# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.python_eval import PythonEval
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.tasks.test_base import TaskTest


class PythonEvalTest(TaskTest):
  @classmethod
  def task_type(cls):
    return PythonEval

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'python_library': PythonLibrary,
                                            'python_binary': PythonBinary})

  def test(self):
    python_eval = self.prepare_task(targets=[])
    compiled = python_eval.execute()
    self.assertEqual(0, len(compiled))
