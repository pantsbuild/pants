# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.engine.round_manager import RoundManager
from pants.util.contextutil import pushd, temporary_dir
from pants_test.tasks.test_base import TaskTest


class JvmRunTest(TaskTest):
  @classmethod
  def task_type(cls):
    return JvmRun

  def test_cmdline_only(self):
    jvm_binary = self.make_target('src/java/com/pants:binary', JvmBinary, main="com.pants.Binary")
    jvm_run = self.prepare_task(args=['--test-only-write-cmd-line=a'],
                                targets=[jvm_binary],
                                build_graph=self.build_graph)

    round_manager = RoundManager(jvm_run.context)
    jvm_run.prepare(self.options, round_manager)

    self.populate_compile_classpath(context=jvm_run.context, classpath=['bob', 'fred'])

    with temporary_dir() as pwd:
      with pushd(pwd):
        cmdline_file = os.path.join(pwd, 'a')
        self.assertFalse(os.path.exists(cmdline_file))
        jvm_run.execute()
        self.assertTrue(os.path.exists(cmdline_file))
        with open(cmdline_file) as fp:
          contents = fp.read()
          expected_suffix = 'java -cp bob:fred com.pants.Binary'
          self.assertEquals(expected_suffix, contents[-len(expected_suffix):])
