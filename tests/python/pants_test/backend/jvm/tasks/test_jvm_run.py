# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.util.contextutil import pushd, temporary_dir
from pants_test.tasks.task_test_base import TaskTestBase


class JvmRunTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return JvmRun

  def setUp(self):
    super(JvmRunTest, self).setUp()

  @contextmanager
  def setup_cmdline_run(self, **options):
    """Run the JvmRun task in command line only mode  with the specified extra options.
    :returns: the command line string
    """
    self.set_options(only_write_cmd_line='a', **options)
    jvm_binary = self.make_target('src/java/org/pantsbuild:binary', JvmBinary,
                                  main='org.pantsbuild.Binary')
    context = self.context(target_roots=[jvm_binary])
    jvm_run =  self.create_task(context, 'unused')
    self._cmdline_classpath = [os.path.join(self.build_root, c) for c in ['bob', 'fred']]
    self.populate_compile_classpath(context=jvm_run.context, classpath=self._cmdline_classpath)
    with temporary_dir() as pwd:
      with pushd(pwd):
        cmdline_file = os.path.join(pwd, 'a')
        self.assertFalse(os.path.exists(cmdline_file))
        jvm_run.execute()
        self.assertTrue(os.path.exists(cmdline_file))
        with open(cmdline_file) as fp:
          contents = fp.read()
          yield contents

  def test_cmdline_only(self):
    with self.setup_cmdline_run() as cmdline:
      expected_suffix = 'java -cp {} org.pantsbuild.Binary'.format(
        os.path.pathsep.join(self._cmdline_classpath))
      self.assertEquals(expected_suffix, cmdline[-len(expected_suffix):])

  def test_opt_main(self):
    with self.setup_cmdline_run(main='org.pantsbuild.OptMain') as cmdline:
      expected_suffix = 'java -cp {} org.pantsbuild.OptMain'.format(
        os.path.pathsep.join(self._cmdline_classpath))
      self.assertEquals(expected_suffix, cmdline[-len(expected_suffix):])
