# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import temporary_file
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.tasks.go_go import GoEnv, GoGo, GoInteropTask


class GoInteropTaskTest(TaskTestBase):
  class FakeGoInteropTask(GoInteropTask):
    def __init__(self, *args, **kwargs):
      super(GoInteropTaskTest.FakeGoInteropTask, self).__init__(*args, **kwargs)
      self._called_with = None

    def execute_with_go_env(self, go_path, import_paths, args, **kwargs):
      self._called_with = go_path, import_paths, args, kwargs

    @property
    def called_with(self):
      return self._called_with

  @classmethod
  def task_type(cls):
    return cls.FakeGoInteropTask

  def test_no_targets(self):
    task = self.create_task(self.context(passthru_args=['vim']))
    with self.assertRaises(GoInteropTask.MissingArgsError):
      task.execute()

  def test_no_passthrough_args(self):
    go_binary = self.make_target(spec='src/go:binary', target_type=GoBinary)
    task = self.create_task(self.context(target_roots=[go_binary]))
    with self.assertRaises(GoInteropTask.MissingArgsError):
      task.execute()

  def test_missing_both(self):
    task = self.create_task(self.context())
    with self.assertRaises(GoInteropTask.MissingArgsError):
      task.execute()

  def test_ok(self):
    go_binary = self.make_target(spec='src/go/bob', target_type=GoBinary)
    task = self.create_task(self.context(target_roots=[go_binary], passthru_args=['vim']))
    task.execute()
    self.assertEqual((task.get_gopath(go_binary), ['bob'], ['vim'], {}), task.called_with)


class GoEnvTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return GoEnv

  def test_execute(self):
    bob_binary = self.make_target(spec='src/go/bob', target_type=GoBinary)
    jane_binary = self.make_target(spec='src/go/jane', target_type=GoBinary)
    task = self.create_task(self.context(target_roots=[bob_binary, jane_binary],
                                         passthru_args=['echo', '$GOPATH']))
    with temporary_file() as stdout:
      task.execute(stdout=stdout)
      stdout.close()
      with open(stdout.name) as output:
        self.assertEqual(output.read().strip(),
                         os.pathsep.join([task.get_gopath(bob_binary),
                                          task.get_gopath(jane_binary)]))


class GoGoTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return GoGo

  def test_execute(self):
    bob_binary = self.make_target(spec='src/go/bob', target_type=GoBinary)
    jane_binary = self.make_target(spec='src/go/jane', target_type=GoBinary)

    # A task to execute `go env GOPATH`.
    task = self.create_task(self.context(target_roots=[bob_binary, jane_binary],
                                         passthru_args=['env', 'GOPATH']))
    with temporary_file() as stdout:
      task.execute(stdout=stdout)
      stdout.close()
      with open(stdout.name) as output:
        self.assertEqual(output.read().strip(),
                         os.pathsep.join([task.get_gopath(bob_binary),
                                          task.get_gopath(jane_binary)]))
