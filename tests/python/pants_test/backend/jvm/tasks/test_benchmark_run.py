# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.benchmark_run import BenchmarkRun
from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class BenchmarkRunTest(JvmToolTaskTestBase):

  @classmethod
  def task_type(cls):
    return BenchmarkRun

  def test_benchmark_complains_on_python_target(self):
    self.make_target('foo:hello', target_type=Target)

    self.set_options(target='<unused, but required>')
    context = self.context(target_roots=[self.target('foo:hello')])
    self.populate_runtime_classpath(context)

    with self.assertRaises(TaskError):
      self.execute(context)
