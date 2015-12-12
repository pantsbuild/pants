# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.jvm_prep_command import JvmPrepCommand
from pants.backend.jvm.tasks.run_jvm_prep_command import RunJvmPrepCommandBase
from pants.base.exceptions import TargetDefinitionException
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.tasks.task_test_base import TaskTestBase


class FakeRunJvmPrepCommand(RunJvmPrepCommandBase):
  goal = 'test'


class JvmPrepCommandTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return FakeRunJvmPrepCommand

  def test_valid_target(self):
    self.make_target('foo', JvmPrepCommand, mainclass='org.pantsbuild.FooMain')

  def test_invalid_target(self):
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'mainclass must be specified'):
      self.make_target('foo', JvmPrepCommand,)

    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'.*goal must be one of.*'):
      self.make_target('foo', JvmPrepCommand, mainclass='org.pantsbuild.FooMain', goal='baloney')

  def test_isprep(self):
    tgt1 = self.make_target('tgt1', JvmPrepCommand, mainclass='org.pantsbuild.FooMain')
    tgt2 = self.make_target('tgt2', JvmPrepCommand, mainclass='org.pantsbuild.FooMain', goal='binary')
    tgt3 = self.make_target('tgt3', JvmBinary)
    task = self.create_task(context=self.context())

    self.assertTrue(task.is_prep(tgt1))
    self.assertFalse(task.is_prep(tgt2))
    self.assertFalse(task.is_prep(tgt3))
