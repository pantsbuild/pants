# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from six.moves import range

from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.prep_command import PrepCommand
from pants.build_graph.target import Target
from pants.core_tasks.run_prep_command import RunPrepCommandBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch
from pants_test.tasks.task_test_base import TaskTestBase


class FakeRunPrepCommand(RunPrepCommandBase):
  goal = 'test'


class RunPrepCommandTest(TaskTestBase):

  def setUp(self):
    super (RunPrepCommandTest, self).setUp()
    # This is normally taken care of in RunPrepCommandBase.register_options() when running pants,
    # but these don't get called in testing unless you call `self.create_task()`.
    # Some of these unit tests need to create targets before creating the task.
    PrepCommand.add_goal('test')
    PrepCommand.add_goal('binary')

  def tearDown(self):
    PrepCommand.reset()

  @classmethod
  def task_type(cls):
    return FakeRunPrepCommand

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'prep_command': PrepCommand,
      },
    )

  def test_prep_order(self):
    with temporary_dir() as workdir:
      with temporary_dir() as tmp:
        files = [os.path.join(tmp, 'file%s' % i) for i in range(3)]
        touch(files[0])
        a = self.make_target('a', dependencies=[], target_type=PrepCommand,
                             prep_executable='mv', prep_args=[files[0], files[1]])
        b = self.make_target('b', dependencies=[a], target_type=PrepCommand,
                             prep_executable='mv', prep_args=[files[1], files[2]])

        context = self.context(target_roots=[b])
        task = self.create_task(context=context, workdir=workdir)
        task.execute()
        self.assertTrue(os.path.exists(files[2]))

  def test_prep_environ(self):
    with temporary_dir() as workdir:
      a = self.make_target('a', dependencies=[], target_type=PrepCommand,
                           prep_executable='echo',
                           prep_args=['-n', 'test_prep_env_var=fleem'],
                           prep_environ=True)

      context = self.context(target_roots=[a])
      task = self.create_task(context=context, workdir=workdir)
      task.execute()
      self.assertEquals('fleem', os.environ['test_prep_env_var'])

  def test_prep_no_command(self):
    with self.assertRaises(TaskError):
      a = self.make_target('a', dependencies=[], target_type=PrepCommand,
                           prep_executable='no_such_executable!$^!$&!$#^$#%!%@!', prep_args=[])

      context = self.context(target_roots=[a])
      task = self.create_task(context=context, workdir='')
      task.execute()

  def test_prep_command_fails(self):
    with self.assertRaises(TaskError):
      a = self.make_target('a', dependencies=[], target_type=PrepCommand,
                           prep_executable='mv', prep_args=['/non/existent/file/name',
                                                            '/bogus/destination/place'])

      context = self.context(target_roots=[a])
      task = self.create_task(context=context, workdir='')
      task.execute()

  def test_valid_target(self):
    self.make_target('foo', PrepCommand, prep_executable='foo.sh')

  def test_invalid_target(self):
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'prep_executable must be specified'):
      self.make_target('foo', PrepCommand,)

    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'.*Got goal "baloney". Goal must be one of.*'):
      self.make_target('foo', PrepCommand, prep_executable='foo.sh', goal='baloney')

  def test_runnable_prep_cmd(self):
    test_prep_cmd = self.make_target('test-prep-cmd', PrepCommand, prep_executable='foo.sh')
    binary_prep_cmd = self.make_target('binary-prep-cmd', PrepCommand, prep_executable='foo.sh', goal='binary')
    not_a_prep_cmd = self.make_target('not-a-prep-cmd', Target)
    task = self.create_task(context=self.context())

    self.assertTrue(task.runnable_prep_cmd(test_prep_cmd))
    # this target is a prep command, but not for a goal that is runnable in this task subclass
    self.assertFalse(task.runnable_prep_cmd(binary_prep_cmd))
    self.assertFalse(task.runnable_prep_cmd(not_a_prep_cmd))
