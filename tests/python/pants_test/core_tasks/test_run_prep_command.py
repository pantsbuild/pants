# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from six.moves import range

from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.prep_command import PrepCommand
from pants.core_tasks.run_prep_command import RunPrepCommand
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch
from pants_test.tasks.task_test_base import TaskTestBase


class RunPrepCommandTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return RunPrepCommand

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
