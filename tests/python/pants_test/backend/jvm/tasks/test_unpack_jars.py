# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pants.backend.jvm.tasks.unpack_jars import UnpackJars
from pants.engine.round_manager import RoundManager
from pants.util.contextutil import temporary_dir
from pants_test.task_test_base import TaskTestBase


class UnpackJarsTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return UnpackJars

  def test_simple(self):
    with temporary_dir() as workdir:
      unpack_task = self.create_task(self.context(), workdir)
      round_manager = RoundManager(self.context())
      unpack_task.prepare(self.options, round_manager)

  def test_invalid_pattern(self):
    with self.assertRaises(UnpackJars.InvalidPatternError):
      UnpackJars._compile_patterns([45])

  def test_unpack_filter(self):
    def run_filter(filename, include_patterns=[], exclude_patterns=[]):
      return UnpackJars._unpack_filter(
        filename,
        UnpackJars._compile_patterns(include_patterns),
        UnpackJars._compile_patterns(exclude_patterns))

    # If no patterns are specified, everything goes through
    self.assertTrue(run_filter("foo/bar.java"))

    self.assertTrue(run_filter("foo/bar.java",
                               include_patterns=["**/*.java"]))
    self.assertTrue(run_filter("bar.java",
                                include_patterns=["**/*.java"]))
    self.assertTrue(run_filter("bar.java",
                               include_patterns=["**/*.java", "*.java"]))
    self.assertFalse(run_filter("foo/bar.java",
                                exclude_patterns=["**/bar.*"]))
    self.assertFalse(run_filter("foo/bar.java",
                                include_patterns=["**/*/java"],
                                exclude_patterns=["**/bar.*"]))
